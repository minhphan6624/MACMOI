from dataclasses import dataclass
from enum import Enum

from .execution import ExecutionCommand, ExecutionManager
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

    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"

@dataclass
class MissionRuntime:
    """In-memory state for one active mission run."""

    mission_id: str
    status: MissionStatus
    tasks: dict[str, TransportItemTask]
    world: MissionWorld


class MissionManager:
    """Coordinates mission lifecycle, task scheduling, and command completion."""

    def __init__(
        self,
        runtime: MissionRuntime,
        scheduler: TransportTaskScheduler | None = None,
        execution_manager: ExecutionManager | None = None,
    ):
        self.runtime = runtime
        self.scheduler = scheduler or TransportTaskScheduler()
        self.execution_manager = execution_manager or ExecutionManager()
        self.task_runner = TransportTaskBtRunner(runtime.world, self.execution_manager)

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
        
        # Create tasks for each Package
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

        # Mission-layer beliefs of the main objecst
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

    def start(self) -> list[ExecutionCommand]:
        """Start a ready mission and return any commands it immediately emits."""

        if self.runtime.status == MissionStatus.READY:
            self.runtime.status = MissionStatus.RUNNING

        return self.tick()

    def tick(self) -> list[ExecutionCommand]:
        """Advance mission logic and return newly emitted execution commands."""

        # Do nothing if the current mission is already running
        if self.runtime.status != MissionStatus.RUNNING:
            return []
            
        # If All Task succeeded, mark mission as completed
        if all(task.status == MissionTaskStatus.SUCCEEDED for task in self.runtime.tasks.values()):
            self.runtime.status = MissionStatus.COMPLETED
            return []

        # If any task is running or blocked, try to advance it
        for task in self.runtime.tasks.values():
            if task.status in (MissionTaskStatus.RUNNING, MissionTaskStatus.BLOCKED):
                commands = self.task_runner.advance(task)
                
                if commands:
                    # Return exising command and possibly start another ready task if posisble
                    task = self.scheduler.next_ready_task(self.runtime.tasks, self.runtime.world)
                    
                    if task is None:
                        return commands
                    
                    return [*commands, *self.task_runner.start(task)]
                    

        # Otherwise prompt the scheduler for next task
        task = self.scheduler.next_ready_task(self.runtime.tasks, self.runtime.world)
        
        if task is None:
            return []

        # Return a list of ExecutionComamnd for the node to send to rmf if there is a task
        return self.task_runner.start(task)

    def complete_command(self, command_id: str) -> list[ExecutionCommand]:
        """
        Apply a completed execution command and continue mission progress.    
        Called when a move/load/unload command succeeds.
        """
        
        # Ignore unkonwn command completions
        # This can happen if an old/stale/foreign completion arrives.
        if command_id not in self.execution_manager.commands:
            return []
        
        # Ignore duplicate or terminal completeions
        command = self.execution_manager.commands[command_id]
        if not self.execution_manager.mark_succeeded(command_id):
            return []
        
        # Ignore a command whose task no longer exists. 
        task = self.runtime.tasks.get(command.task_id)
        if task is None:
            return []
        
        # Delegate handling for the runner
        commands = self.task_runner.handle_command_succeeded(task, command)

        if commands:
            task = self.scheduler.next_ready_task(self.runtime.tasks, self.runtime.world)
            if task is None:
                return commands
            
            return [*commands, *self.task_runner.start(task)]
        else: 
            self.tick()
    
        
