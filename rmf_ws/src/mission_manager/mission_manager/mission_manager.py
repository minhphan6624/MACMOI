from dataclasses import dataclass
from enum import Enum

from .execution import ExecutionCommand, ExecutionCommandType, ExecutionManager
from .mission_events import (
    ExecutionCommandCancelled,
    ExecutionCommandCompleted,
    ExecutionCommandFailed,
    MissionStartRequested,
    OperatorAbortRequested,
    OperatorPauseRequested,
    OperatorRobotPauseRequested,
    OperatorRobotResumeRequested,
    OperatorResumeRequested,
)
from .mission_definition import (
    DESTINATION_WAYPOINT,
    DOWNSTREAM_WAIT_WAYPOINT,
    DOWNSTREAM_HOME_WAYPOINT,
    DOWNSTREAM_ROBOT,
    SOURCE_WAYPOINT,
    TRANSFER_WAYPOINT,
    UPSTREAM_WAIT_WAYPOINT,
    UPSTREAM_HOME_WAYPOINT,
    UPSTREAM_ROBOT,
)
from .mission_tasks import MissionTaskStatus, TransportItemTask
from .resources import ResourceState
from .scheduler import TransportTaskScheduler
from .transport_bt_runner import TransportTaskBtRunner
from .world import MissionWorld, PackageState, RobotState


class MissionStatus(Enum):
    """High-level lifecycle state for one mission run."""

    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


@dataclass
class MissionRuntime:
    """In-memory state for one active mission run."""

    mission_id: str
    status: MissionStatus
    tasks: dict[str, TransportItemTask]
    world: MissionWorld


class MissionManager:
    """Coordinates mission lifecycle, task scheduling, and mission events."""

    def __init__(
        self,
        runtime: MissionRuntime,
        scheduler: TransportTaskScheduler | None = None,
        execution_manager: ExecutionManager | None = None,
        max_arrival_retries: int = 2,
    ):
        self.runtime = runtime
        self.scheduler = scheduler or TransportTaskScheduler()
        self.execution_manager = execution_manager or ExecutionManager()
        self.task_runner = TransportTaskBtRunner(runtime.world, self.execution_manager)
        self.max_arrival_retries = max_arrival_retries

    def handle_event(self, event) -> list[ExecutionCommand]:
        """Apply a mission event and return newly emitted execution commands."""

        if isinstance(event, MissionStartRequested):
            return self._handle_start_requested(event)
        if isinstance(event, ExecutionCommandCompleted):
            return self._handle_command_completed(event)
        if isinstance(event, ExecutionCommandFailed):
            return self._handle_command_failed(event)
        if isinstance(event, ExecutionCommandCancelled):
            return self._handle_command_cancelled(event)
        if isinstance(event, OperatorPauseRequested):
            return self._handle_operator_pause_requested(event)
        if isinstance(event, OperatorResumeRequested):
            return self._handle_operator_resume_requested(event)
        if isinstance(event, OperatorRobotPauseRequested):
            return self._handle_operator_robot_pause_requested(event)
        if isinstance(event, OperatorRobotResumeRequested):
            return self._handle_operator_robot_resume_requested(event)
        if isinstance(event, OperatorAbortRequested):
            return self._handle_operator_abort_requested(event)
        return []

    # ----- Internal Event Handlers -----
    def _handle_start_requested(
        self,
        event: MissionStartRequested,
    ) -> list[ExecutionCommand]:
        if self.runtime.status == MissionStatus.READY:
            self.runtime.status = MissionStatus.RUNNING

        return self._advance()

    # ----- handlers for ExecutionCommand events -----
    def _handle_command_completed(
        self,
        event: ExecutionCommandCompleted,
    ) -> list[ExecutionCommand]:
        command_id = event.command_id

        if command_id not in self.execution_manager.commands:
            return []

        command = self.execution_manager.commands[command_id]
        if not self.execution_manager.mark_succeeded(command_id):
            return []

        task = self.runtime.tasks.get(command.task_id)
        if task is None:
            return []

        robot_paused = self.runtime.world.robots[command.robot_id].paused
        if (
            self.runtime.status in (MissionStatus.PAUSED, MissionStatus.ABORTED)
            or robot_paused
        ):
            self.task_runner.apply_command_success(task, command)
            if self.runtime.status == MissionStatus.PAUSED or robot_paused:
                task.status = MissionTaskStatus.RUNNING
            else:
                task.status = MissionTaskStatus.CANCELLED
            return []

        if not self.task_runner.apply_command_success(task, command):
            return self._advance()

        commands = self.task_runner.advance(task)
        if commands:
            task = self.scheduler.next_ready_task(
                self.runtime.tasks,
                self.runtime.world,
            )
            if task is None:
                return commands

            return [*commands, *self.task_runner.start(task)]

        return self._advance()

    def _handle_command_failed(self, event: ExecutionCommandFailed) -> list[ExecutionCommand]:
        command_id = event.command_id
        error = event.error

        if command_id not in self.execution_manager.commands:
            return []

        command = self.execution_manager.commands[command_id]
        if not self.execution_manager.mark_failed(command_id, error):
            return []

        task = self.runtime.tasks.get(command.task_id)
        if task is None:
            return []

        if task.active_command_id != command_id:
            return []

        task.active_command_id = None
        if (
            error == "arrival_not_verified"
            and command.command_type == ExecutionCommandType.MOVE_ROBOT
            and command.target is not None
        ):
            retry_key = f"arrival_retry:{command.target}"
            retries = int(task.bt_blackboard.get(retry_key, 0))

            if retries < self.max_arrival_retries:
                task.bt_blackboard[retry_key] = retries + 1
                task.status = MissionTaskStatus.RUNNING

                retry = self.execution_manager.create_move(
                    command.task_id,
                    command.robot_id,
                    command.target,
                )

                task.active_command_id = retry.command_id
                return [retry]

        self._fail_task(task, command, error)
        return []

    def _handle_command_cancelled(
        self,
        event: ExecutionCommandCancelled,
    ) -> list[ExecutionCommand]:
        command_id = event.command_id
        reason = event.reason

        if command_id not in self.execution_manager.commands:
            return []

        command = self.execution_manager.commands[command_id]
        if not self.execution_manager.mark_cancelled(command_id, reason):
            return []

        task = self.runtime.tasks.get(command.task_id)
        if task is None:
            return []

        if task.active_command_id == command_id:
            task.active_command_id = None

        if reason in ("operator_pause", "operator_robot_pause"):
            task.status = MissionTaskStatus.RUNNING
            robot = self.runtime.world.robots[command.robot_id]
            if reason == "operator_robot_pause" and not robot.paused:
                return self._advance()
            return []

        if reason == "operator_abort":
            task.status = MissionTaskStatus.CANCELLED
            return []

        self._fail_task(task, command, reason)
        return []

    def _fail_task(
        self,
        task: TransportItemTask,
        command: ExecutionCommand,
        reason: str,
    ) -> None:
        task.status = MissionTaskStatus.FAILED
        task.blocked_reason = reason
        task.blocked_by = command.robot_id
        self.runtime.status = MissionStatus.FAILED

    # ---- Handlers for operator commands 
    def _handle_operator_pause_requested(
        self,
        event: OperatorPauseRequested,
    ) -> list[ExecutionCommand]:
        if self.runtime.status == MissionStatus.RUNNING:
            self.runtime.status = MissionStatus.PAUSED
        return []

    def _handle_operator_resume_requested(
        self,
        event: OperatorResumeRequested,
    ) -> list[ExecutionCommand]:
        if self.runtime.status == MissionStatus.PAUSED:
            self.runtime.status = MissionStatus.RUNNING
            return self._advance()
        return []

    def _handle_operator_robot_pause_requested(
        self,
        event: OperatorRobotPauseRequested,
    ) -> list[ExecutionCommand]:
        robot = self.runtime.world.robots.get(event.robot_id)
        if robot is not None:
            robot.paused = True
        return []

    def _handle_operator_robot_resume_requested(
        self,
        event: OperatorRobotResumeRequested,
    ) -> list[ExecutionCommand]:
        robot = self.runtime.world.robots.get(event.robot_id)
        if robot is None or not robot.paused:
            return []
        robot.paused = False
        return self._advance()

    def _handle_operator_abort_requested(
        self,
        event: OperatorAbortRequested,
    ) -> list[ExecutionCommand]:
        if self.runtime.status in (
            MissionStatus.READY,
            MissionStatus.RUNNING,
            MissionStatus.PAUSED,
            MissionStatus.FAILED,
        ):
            self.runtime.status = MissionStatus.ABORTED
            for task in self.runtime.tasks.values():
                if task.status == MissionTaskStatus.SUCCEEDED:
                    continue
                task.status = MissionTaskStatus.CANCELLED
        return []

    
    @classmethod
    def create_default(
        cls,
        mission_id: str,
        total_packages: int,
        upstream_robot: str = UPSTREAM_ROBOT,
        downstream_robot: str = DOWNSTREAM_ROBOT,
    ):
        """Build the fixed two-robot package handoff mission."""

        tasks = {}
        items = {}
        
        for index in range(1, total_packages + 1):
            item_id = f"P{index}"
            items[item_id] = PackageState(item_id, SOURCE_WAYPOINT)

            tasks[f"{item_id}:source_to_transfer"] = TransportItemTask(
                task_id=f"{item_id}:source_to_transfer",
                item_id=item_id,
                pickup=SOURCE_WAYPOINT,
                dropoff=TRANSFER_WAYPOINT,
                robot_id=upstream_robot,
            )

            tasks[f"{item_id}:transfer_to_destination"] = TransportItemTask(
                task_id=f"{item_id}:transfer_to_destination",
                item_id=item_id,
                pickup=TRANSFER_WAYPOINT,
                dropoff=DESTINATION_WAYPOINT,
                robot_id=downstream_robot,
            )

        world = MissionWorld(
            robots={
                upstream_robot: RobotState(upstream_robot, UPSTREAM_HOME_WAYPOINT),
                downstream_robot: RobotState(downstream_robot, DOWNSTREAM_HOME_WAYPOINT),
            },
            items=items,
            resources={
                TRANSFER_WAYPOINT: ResourceState(
                    resource_id=TRANSFER_WAYPOINT,
                    robot_capacity=1,
                    package_capacity=1,
                    wait_waypoints={
                        upstream_robot: UPSTREAM_WAIT_WAYPOINT,
                        downstream_robot: DOWNSTREAM_WAIT_WAYPOINT,
                    },
                )
            },
        )

        return cls(MissionRuntime(mission_id, MissionStatus.READY, tasks, world))

    def _advance(self) -> list[ExecutionCommand]:
        """Advance mission logic and return newly emitted execution commands."""

        if self.runtime.status != MissionStatus.RUNNING:
            return []

        if all(
            task.status == MissionTaskStatus.SUCCEEDED
            for task in self.runtime.tasks.values()
        ):
            self.runtime.status = MissionStatus.COMPLETED
            return []

        for task in self.runtime.tasks.values():
            if task.status in (MissionTaskStatus.RUNNING, MissionTaskStatus.BLOCKED):
                if self.runtime.world.robots[task.robot_id].paused:
                    continue
                commands = self.task_runner.advance(task)

                if commands:
                    task = self.scheduler.next_ready_task( self.runtime.tasks, self.runtime.world)

                    if task is None:
                        return commands

                    return [*commands, *self.task_runner.start(task)]

        task = self.scheduler.next_ready_task(self.runtime.tasks, self.runtime.world)

        if task is None:
            return []

        return self.task_runner.start(task)
