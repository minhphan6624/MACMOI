from dataclasses import dataclass

from .execution import ExecutionCommand, ExecutionManager
from .mission_definition import (
    DESTINATION_WAYPOINT,
    DOWNSTREAM_HOME_WAYPOINT,
    DOWNSTREAM_ROBOT,
    SOURCE_WAYPOINT,
    TRANSFER_WAYPOINT,
    UPSTREAM_HOME_WAYPOINT,
    UPSTREAM_ROBOT,
)
from .mission_tasks import MissionStatus, MissionTaskStatus, TransportItemTask
from .resources import ResourceState, ResourceType
from .scheduler import TransportTaskScheduler
from .transport_bt_runner import TransportTaskBtRunner
from .world import RuntimeWorld, WorldItemState, WorldRobotState


@dataclass
class MissionRuntime:
    mission_id: str
    status: MissionStatus
    tasks: dict[str, TransportItemTask]
    world: RuntimeWorld


class MissionOrchestrator:
    def __init__(
        self,
        runtime: MissionRuntime,
        scheduler: TransportTaskScheduler | None = None,
        execution: ExecutionManager | None = None,
    ):
        self.runtime = runtime
        self.scheduler = scheduler or TransportTaskScheduler()
        self.execution = execution or ExecutionManager()
        self.task_runner = TransportTaskBtRunner(runtime.world, self.execution)

    @classmethod
    def create_default(
        cls,
        mission_id: str,
        total_packages: int,
        upstream_robot: str = UPSTREAM_ROBOT,
        downstream_robot: str = DOWNSTREAM_ROBOT,
    ):
        tasks = {}
        items = {}
        for index in range(1, total_packages + 1):
            item_id = f"P{index}"
            items[item_id] = WorldItemState(item_id, SOURCE_WAYPOINT)
            tasks[f"{item_id}:source_to_transfer"] = TransportItemTask(
                task_id=f"{item_id}:source_to_transfer",
                item_id=item_id,
                pickup=SOURCE_WAYPOINT,
                dropoff=TRANSFER_WAYPOINT,
                robot_id=upstream_robot,
                required_resources=[TRANSFER_WAYPOINT],
            )
            tasks[f"{item_id}:transfer_to_destination"] = TransportItemTask(
                task_id=f"{item_id}:transfer_to_destination",
                item_id=item_id,
                pickup=TRANSFER_WAYPOINT,
                dropoff=DESTINATION_WAYPOINT,
                robot_id=downstream_robot,
                required_resources=[TRANSFER_WAYPOINT],
            )

        world = RuntimeWorld(
            robots={
                upstream_robot: WorldRobotState(upstream_robot, UPSTREAM_HOME_WAYPOINT),
                downstream_robot: WorldRobotState(downstream_robot, DOWNSTREAM_HOME_WAYPOINT),
            },
            items=items,
            resources={
                TRANSFER_WAYPOINT: ResourceState(
                    resource_id=TRANSFER_WAYPOINT,
                    resource_type=ResourceType.TRANSFER_ZONE,
                    robot_capacity=1,
                    package_capacity=1,
                )
            },
        )
        return cls(MissionRuntime(mission_id, MissionStatus.READY, tasks, world))

    def start(self) -> list[ExecutionCommand]:
        if self.runtime.status == MissionStatus.READY:
            self.runtime.status = MissionStatus.RUNNING

        return self.tick()

    def tick(self) -> list[ExecutionCommand]:
        if self.runtime.status != MissionStatus.RUNNING:
            return []
            
        if all(task.status == MissionTaskStatus.SUCCEEDED for task in self.runtime.tasks.values()):
            self.runtime.status = MissionStatus.COMPLETED
            return []

        for task in self.runtime.tasks.values():
            if task.status in (MissionTaskStatus.RUNNING, MissionTaskStatus.BLOCKED):
                commands = self.task_runner.advance(task)
                if commands:
                    return commands

        task = self.scheduler.next_ready_task(self.runtime.tasks, self.runtime.world)
        if task is None:
            return []

        return self.task_runner.start(task)

    def complete_command(self, command_id: str) -> list[ExecutionCommand]:
        if command_id not in self.execution.commands:
            return []
        command = self.execution.commands[command_id]
        if not self.execution.mark_succeeded(command_id):
            return []
        task = self.runtime.tasks.get(command.task_id)
        if task is None:
            return []
        commands = self.task_runner.handle_command_succeeded(task, command)
        return commands or self.tick()
