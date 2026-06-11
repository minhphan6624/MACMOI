from .behavior_tree import BtNode, BtResult, BtStatus, MemorySequence, TransportTaskContext
from .execution import ExecutionCommand, ExecutionCommandType, ExecutionManager
from .mission_definition import (
    DOWNSTREAM_ROBOT,
    TRANSFER_DOWNSTREAM_EXIT_WAYPOINT,
    TRANSFER_UPSTREAM_EXIT_WAYPOINT,
    TRANSFER_WAYPOINT,
    UPSTREAM_ROBOT,
)
from .mission_tasks import MissionTaskStatus, TransportItemTask, TransportTaskPhase
from .resources import ResourceAccessStatus
from .world import MissionWorld, RobotStatus


class TransportTaskBtRunner:
    """Runs the behavior-tree sequence for one transport task."""

    def __init__(self, world: MissionWorld, execution: ExecutionManager):
        """Create the fixed transport sequence used by each package task."""

        self.world = world
        self.execution = execution
        self.tree = MemorySequence(
            "transport_item",
            [
                AssignRobot(),
                RequestResourceAccess("pickup"),
                MoveTo("pickup", TransportTaskPhase.MOVE_TO_PICKUP),
                MarkResourceOccupied("pickup"),
                HandleItem("load", TransportTaskPhase.LOAD_ITEM),
                UpdateResourceAfterHandling("pickup", "load"),
                VacateResourceIfManaged("pickup"),
                ReleaseResourceIfManaged("pickup"),
                RequestResourceAccess("dropoff"),
                MoveTo("dropoff", TransportTaskPhase.MOVE_TO_DROPOFF),
                MarkResourceOccupied("dropoff"),
                HandleItem("unload", TransportTaskPhase.UNLOAD_ITEM),
                UpdateResourceAfterHandling("dropoff", "unload"),
                VacateResourceIfManaged("dropoff"),
                ReleaseResourceIfManaged("dropoff"),
                ReleaseRobot(),
                MarkTaskSucceeded(),
            ],
        )

    def start(self, task: TransportItemTask) -> list[ExecutionCommand]:
        """Mark a task running and advance it for the first time."""

        if task.robot_id is None:
            return []
        task.status = MissionTaskStatus.RUNNING
        task.phase = TransportTaskPhase.ACQUIRE_PICKUP
        return self.advance(task)

    def advance(self, task: TransportItemTask) -> list[ExecutionCommand]:
        """Tick the task behavior tree and return emitted commands."""

        if task.robot_id is None:
            return []
        result = self.tree.tick(TransportTaskContext(task, self.world, self.execution))
        return result.commands

    def handle_command_succeeded(
        self,
        task: TransportItemTask,
        command: ExecutionCommand,
    ) -> list[ExecutionCommand]:
        """Update world state for a completed command, then advance the task."""

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
    """Claims the task's assigned robot when it is idle."""

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Assign the robot to the task or wait until it becomes idle."""

        task = ctx.task
        robot = ctx.world.robots[task.robot_id]

        if robot.active_task_id == task.task_id:
            return BtResult(BtStatus.SUCCESS)
        
        if robot.status != RobotStatus.IDLE:
            return BtResult(BtStatus.RUNNING)
        
        ctx.world.assign_robot(task.robot_id, task.task_id)
        task.status = MissionTaskStatus.RUNNING
        return BtResult(BtStatus.SUCCESS)


class RequestResourceAccess(BtNode):
    """Requests access to a managed pickup or dropoff resource."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Request resource access and set task wait/block details when denied."""

        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources:
            return BtResult(BtStatus.SUCCESS)
        if task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        purpose = self.endpoint
        task.phase = self._acquire_phase()
        decision = ctx.world.resources_manager.request_access(
            resource_id,
            task.robot_id,
            purpose,
            task.item_id,
            task.task_id,
        )
        if decision.status == ResourceAccessStatus.WAIT:
            return self._wait_at_resource_waypoint(ctx, decision)
        if decision.status != ResourceAccessStatus.GRANTED:
            task.status = MissionTaskStatus.BLOCKED
            task.waiting_resource_id = resource_id
            task.waiting_purpose = purpose
            self._set_blocked_details(ctx, decision)
            ctx.world.mark_robot_waiting(task.robot_id, task.task_id)
            return BtResult(BtStatus.RUNNING)

        ctx.world.assign_robot(task.robot_id, task.task_id)
        task.bt_blackboard[acquired_key] = True
        task.waiting_resource_id = None
        task.waiting_purpose = None
        self._clear_blocked_details(task)
        task.status = MissionTaskStatus.RUNNING
        return BtResult(BtStatus.SUCCESS)

    def _wait_at_resource_waypoint(
        self,
        ctx: TransportTaskContext,
        decision,
    ) -> BtResult:
        """Move to a wait waypoint or mark the task blocked at the resource."""

        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        wait_waypoint = decision.target
        task.waiting_resource_id = resource_id
        task.waiting_purpose = self.endpoint
        self._set_blocked_details(ctx, decision)
        if wait_waypoint is None:
            task.status = MissionTaskStatus.BLOCKED
            ctx.world.mark_robot_waiting(task.robot_id, task.task_id)
            return BtResult(BtStatus.RUNNING)
        if ctx.world.robots[task.robot_id].location != wait_waypoint:
            task.status = MissionTaskStatus.RUNNING
            return MoveTo(wait_waypoint, TransportTaskPhase.MOVE_TO_WAIT_POINT).tick(ctx)

        task.phase = TransportTaskPhase.WAIT_FOR_RESOURCE
        task.status = MissionTaskStatus.BLOCKED
        ctx.world.mark_robot_waiting(task.robot_id, task.task_id)
        return BtResult(BtStatus.RUNNING)

    def _acquire_phase(self) -> TransportTaskPhase:
        if self.endpoint == "pickup":
            return TransportTaskPhase.ACQUIRE_PICKUP
        return TransportTaskPhase.ACQUIRE_DROPOFF

    def _set_blocked_details(self, ctx: TransportTaskContext, decision) -> None:
        task = ctx.task
        task.blocked_reason = decision.reason
        task.blocked_by = decision.blocked_by
        task.waiting_at = decision.target
        task.unblock_condition = self._unblock_condition(decision.reason)
        task.next_expected_event = self._next_expected_event(decision.reason)

    def _clear_blocked_details(self, task: TransportItemTask) -> None:
        task.blocked_reason = None
        task.blocked_by = None
        task.waiting_at = None
        task.unblock_condition = None
        task.next_expected_event = None

    def _unblock_condition(self, reason: str | None) -> str | None:
        if reason == "PACKAGE_NOT_AVAILABLE":
            return "package buffered at transfer"
        if reason == "TRANSFER_PACKAGE_FULL":
            return "package removed from transfer buffer"
        if reason in ("TRANSFER_ROBOT_OCCUPIED", "WAITING_FOR_TRANSFER_LEASE"):
            return "transfer robot occupancy and lease released"
        return None

    def _next_expected_event(self, reason: str | None) -> str | None:
        if reason == "PACKAGE_NOT_AVAILABLE":
            return "upstream robot unloads package at transfer"
        if reason == "TRANSFER_PACKAGE_FULL":
            return "downstream robot loads package from transfer"
        if reason == "TRANSFER_ROBOT_OCCUPIED":
            return "robot exits transfer"
        if reason == "WAITING_FOR_TRANSFER_LEASE":
            return "active transfer lease released"
        return None


class MoveTo(BtNode):
    """Emits a move command until the robot reaches the target waypoint."""

    def __init__(self, target: str, phase: TransportTaskPhase):
        self.target = target
        self.phase = phase

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Create a move command unless the robot is already at the target."""

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
    """Emits a package load or unload command."""

    def __init__(self, handling_type: str, phase: TransportTaskPhase):
        self.handling_type = handling_type
        self.phase = phase

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Create a package handling command unless the item is already handled."""

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


class MarkResourceOccupied(BtNode):
    """Marks a managed resource as occupied by the task robot."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Record robot occupancy after resource access has been acquired."""

        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources or not task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        ctx.world.resources_manager.occupy(resource_id, task.robot_id)
        return BtResult(BtStatus.SUCCESS)


class UpdateResourceAfterHandling(BtNode):
    """Updates package occupancy after a load or unload at a resource."""

    def __init__(self, endpoint: str, handling_type: str):
        self.endpoint = endpoint
        self.handling_type = handling_type

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Update the managed resource's package buffer after handling."""

        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources or not task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        if self.handling_type == "load":
            ctx.world.resources_manager.release_item(resource_id, task.item_id)
        elif self.handling_type == "unload":
            ctx.world.resources_manager.buffer_item(resource_id, task.item_id)
        return BtResult(BtStatus.SUCCESS)


class VacateResourceIfManaged(BtNode):
    """Moves the robot to its side-specific exit after using a resource."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Move out of a managed resource when an exit waypoint exists."""

        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        if resource_id not in ctx.world.resources:
            return BtResult(BtStatus.SUCCESS)

        exit_waypoint = self._exit_waypoint(task.robot_id)
        if exit_waypoint is None:
            return BtResult(BtStatus.SUCCESS)
        return MoveTo(exit_waypoint, TransportTaskPhase.MOVE_TO_TRANSFER_EXIT).tick(ctx)

    def _exit_waypoint(self, robot_id: str) -> str | None:
        return transfer_side_waypoint(robot_id)


class ReleaseResourceIfManaged(BtNode):
    """Releases a managed resource lease and robot occupancy."""

    def __init__(self, endpoint: str):
        self.endpoint = endpoint

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        task = ctx.task
        resource_id = getattr(task, self.endpoint)
        acquired_key = f"{self.endpoint}_resource_acquired"
        if resource_id not in ctx.world.resources or not task.bt_blackboard.get(acquired_key):
            return BtResult(BtStatus.SUCCESS)

        ctx.world.resources_manager.release(resource_id, task.robot_id)
        task.bt_blackboard[acquired_key] = False
        return BtResult(BtStatus.SUCCESS)


class ReleaseRobot(BtNode):
    """Marks the task robot as idle."""

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        ctx.world.release_robot(ctx.task.robot_id)
        return BtResult(BtStatus.SUCCESS)


class MarkTaskSucceeded(BtNode):
    """Marks the transport task as complete."""

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        ctx.task.phase = TransportTaskPhase.DONE
        ctx.task.status = MissionTaskStatus.SUCCEEDED
        return BtResult(BtStatus.SUCCESS)


def transfer_side_waypoint(robot_id: str) -> str | None:
    if robot_id == UPSTREAM_ROBOT:
        return TRANSFER_UPSTREAM_EXIT_WAYPOINT
    if robot_id == DOWNSTREAM_ROBOT:
        return TRANSFER_DOWNSTREAM_EXIT_WAYPOINT
    return None
