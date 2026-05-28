from .behavior_tree import BtNode, BtResult, BtStatus, MemorySequence, TransportTaskContext
from .execution import ExecutionCommand, ExecutionCommandType, ExecutionManager
from .mission_definition import STAGING_WAYPOINT, TRANSFER_WAYPOINT
from .mission_tasks import MissionTaskStatus, TransportItemTask, TransportTaskPhase
from .world import RuntimeWorld, WorldRobotStatus


class TransportTaskBtRunner:
    def __init__(self, world: RuntimeWorld, execution: ExecutionManager):
        self.world = world
        self.execution = execution
        self.tree = MemorySequence(
            "transport_item",
            [
                AssignRobot(),
                AcquireResourceIfManaged("pickup"),
                MoveTo("pickup", TransportTaskPhase.MOVE_TO_PICKUP),
                HandleItem("load", TransportTaskPhase.LOAD_ITEM),
                ReleasePickupItemIfManaged(),
                AcquireDropoffOrStage(),
                MoveTo("dropoff", TransportTaskPhase.MOVE_TO_DROPOFF),
                ReleaseResourceOccupancyIfManaged("pickup"),
                HandleItem("unload", TransportTaskPhase.UNLOAD_ITEM),
                VacateDropoffIfNeeded(),
                ReleaseResourceIfManaged("dropoff"),
                ReleaseRobot(),
                MarkTaskSucceeded(),
            ],
        )

    def start(self, task: TransportItemTask) -> list[ExecutionCommand]:
        if task.robot_id is None:
            return []
        task.status = MissionTaskStatus.RUNNING
        task.phase = TransportTaskPhase.ACQUIRE_PICKUP
        return self.advance(task)

    def advance(self, task: TransportItemTask) -> list[ExecutionCommand]:
        if task.robot_id is None:
            return []
        result = self.tree.tick(TransportTaskContext(task, self.world, self.execution))
        return result.commands

    def handle_command_succeeded(
        self,
        task: TransportItemTask,
        command: ExecutionCommand,
    ) -> list[ExecutionCommand]:
        if task.active_command_id != command.command_id:
            return []

        task.active_command_id = None
        if command.command_type == ExecutionCommandType.MOVE_ROBOT and command.target is not None:
            self.world.move_robot(command.robot_id, command.target)
        elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
            if command.handling_type == "load" and command.item_id is not None:
                self.world.load_item(command.robot_id, command.item_id)
            elif command.handling_type == "unload" and command.item_id is not None:
                self.world.unload_item(command.robot_id, command.item_id, task.dropoff)

        return self.advance(task)


class AssignRobot(BtNode):
    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        robot = ctx.world.robots[task.robot_id]
        if robot.active_task_id == task.task_id:
            return BtResult(BtStatus.SUCCESS)
        if robot.status != WorldRobotStatus.IDLE:
            return BtResult(BtStatus.RUNNING)
        ctx.world.assign_robot(task.robot_id, task.task_id)
        task.status = MissionTaskStatus.RUNNING
        return BtResult(BtStatus.SUCCESS)


class AcquireResourceIfManaged(BtNode):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources:
            return BtResult(BtStatus.SUCCESS)
        if task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        purpose = self.endpoint
        phase = (
            TransportTaskPhase.ACQUIRE_PICKUP
            if self.endpoint == "pickup"
            else TransportTaskPhase.ACQUIRE_DROPOFF
        )
        task.phase = phase
        if not ctx.world.can_acquire(resource_id, task.robot_id, purpose, task.item_id):
            return BtResult(BtStatus.FAILURE)

        ctx.world.occupy_resource(resource_id, task.robot_id)
        ctx.world.assign_robot(task.robot_id, task.task_id)
        task.bt_blackboard[acquired_key] = True
        task.status = MissionTaskStatus.RUNNING
        return BtResult(BtStatus.SUCCESS)


class AcquireDropoffOrStage(BtNode):
    def __init__(self):
        self.acquire = AcquireResourceIfManaged("dropoff")
        self.move_to_staging = MoveTo(STAGING_WAYPOINT, TransportTaskPhase.MOVE_TO_STAGING)

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        result = self.acquire.tick(ctx)
        if result.status == BtStatus.SUCCESS:
            ctx.task.waiting_resource_id = None
            ctx.task.waiting_purpose = None
            return result

        task = ctx.task
        task.waiting_resource_id = task.dropoff
        task.waiting_purpose = "dropoff"
        if ctx.world.robots[task.robot_id].location != STAGING_WAYPOINT:
            task.status = MissionTaskStatus.RUNNING
            return self.move_to_staging.tick(ctx)

        task.phase = TransportTaskPhase.WAIT_FOR_RESOURCE
        task.status = MissionTaskStatus.BLOCKED
        ctx.world.mark_robot_waiting(task.robot_id, task.task_id)
        return BtResult(BtStatus.RUNNING)


class MoveTo(BtNode):
    def __init__(self, target: str, phase: TransportTaskPhase):
        self.target = target
        self.phase = phase

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        target = getattr(task, self.target, self.target)
        task.phase = self.phase
        if ctx.world.robots[task.robot_id].location == target:
            return BtResult(BtStatus.SUCCESS)
        if task.active_command_id is not None:
            return BtResult(BtStatus.RUNNING)

        task.status = MissionTaskStatus.RUNNING
        command = ctx.execution.create_move(task.task_id, task.robot_id, target)
        task.active_command_id = command.command_id
        return BtResult(BtStatus.RUNNING, [command])


class HandleItem(BtNode):
    def __init__(self, handling_type: str, phase: TransportTaskPhase):
        self.handling_type = handling_type
        self.phase = phase

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        item = ctx.world.items[task.item_id]
        if self.handling_type == "load" and item.carried_by == task.robot_id:
            return BtResult(BtStatus.SUCCESS)
        if (
            self.handling_type == "unload"
            and item.carried_by is None
            and item.location == task.dropoff
        ):
            return BtResult(BtStatus.SUCCESS)
        if task.active_command_id is not None:
            return BtResult(BtStatus.RUNNING)

        task.phase = self.phase
        task.status = MissionTaskStatus.RUNNING
        command = ctx.execution.create_handling(
            task.task_id,
            task.robot_id,
            task.item_id,
            self.handling_type,
        )
        task.active_command_id = command.command_id
        return BtResult(BtStatus.RUNNING, [command])


class VacateDropoffIfNeeded(BtNode):
    def __init__(self):
        self.move_to_staging = MoveTo(STAGING_WAYPOINT, TransportTaskPhase.MOVE_TO_STAGING)

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        if ctx.task.dropoff != TRANSFER_WAYPOINT:
            return BtResult(BtStatus.SUCCESS)
        return self.move_to_staging.tick(ctx)


class ReleasePickupItemIfManaged(BtNode):
    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        resource_id = task.pickup
        if resource_id not in ctx.world.resources or not task.bt_blackboard.get("pickup_resource_acquired"):
            return BtResult(BtStatus.SUCCESS)

        ctx.world.release_item(resource_id, task.item_id)
        return BtResult(BtStatus.SUCCESS)


class ReleaseResourceOccupancyIfManaged(BtNode):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources or not task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        ctx.world.release_resource(resource_id, task.robot_id)
        task.bt_blackboard[acquired_key] = False
        return BtResult(BtStatus.SUCCESS)


class ReleaseResourceIfManaged(BtNode):
    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        if resource_id not in ctx.world.resources:
            return BtResult(BtStatus.SUCCESS)

        if self.endpoint == "dropoff":
            ctx.world.buffer_item(resource_id, task.item_id)
        return ReleaseResourceOccupancyIfManaged(self.endpoint).tick(ctx)


class ReleaseRobot(BtNode):
    def tick(self, ctx: TransportTaskContext) -> BtResult:
        ctx.world.release_robot(ctx.task.robot_id)
        return BtResult(BtStatus.SUCCESS)


class MarkTaskSucceeded(BtNode):
    def tick(self, ctx: TransportTaskContext) -> BtResult:
        ctx.task.phase = TransportTaskPhase.DONE
        ctx.task.status = MissionTaskStatus.SUCCEEDED
        return BtResult(BtStatus.SUCCESS)
