from ..rmf_ws.src.mrd_mission_manager.mrd_mission_manager.execution import ExecutionCommand, ExecutionCommandType, ExecutionManager
from ..rmf_ws.src.mrd_mission_manager.mrd_mission_manager.mission_definition import STAGING_WAYPOINT
from ..rmf_ws.src.mrd_mission_manager.mrd_mission_manager.mission_tasks import MissionTaskStatus, TransportItemTask, TransportTaskPhase
from ..rmf_ws.src.mrd_mission_manager.mrd_mission_manager.world import RuntimeWorld


class TransportTaskRunner:
    def __init__(self, world: RuntimeWorld, execution: ExecutionManager):
        self.world = world
        self.execution = execution

    def start(self, task: TransportItemTask) -> list[ExecutionCommand]:
        if task.robot_id is None:
            return []
        self.world.assign_robot(task.robot_id, task.task_id)
        task.status = MissionTaskStatus.RUNNING
        task.phase = TransportTaskPhase.ACQUIRE_PICKUP
        return self.advance(task)

    def advance(self, task: TransportItemTask) -> list[ExecutionCommand]:
        if task.robot_id is None or task.active_command_id is not None:
            return []

        while task.status in (MissionTaskStatus.RUNNING, MissionTaskStatus.BLOCKED):
            if task.phase == TransportTaskPhase.ACQUIRE_PICKUP:
                if self._resource_exists(task.pickup):
                    if not self._acquire_resource(task, task.pickup, "pickup"):
                        return self._stage_or_wait(task, task.pickup, "pickup")
                task.phase = TransportTaskPhase.MOVE_TO_PICKUP

            elif task.phase == TransportTaskPhase.MOVE_TO_PICKUP:
                if self.world.robots[task.robot_id].location == task.pickup:
                    task.phase = TransportTaskPhase.LOAD_ITEM
                    continue
                return [self._create_move(task, task.pickup)]

            elif task.phase == TransportTaskPhase.LOAD_ITEM:
                return [self._create_handling(task, "load")]

            elif task.phase == TransportTaskPhase.ACQUIRE_DROPOFF:
                if self._resource_exists(task.dropoff):
                    if not self._acquire_resource(task, task.dropoff, "dropoff"):
                        return self._stage_or_wait(task, task.dropoff, "dropoff")
                task.phase = TransportTaskPhase.MOVE_TO_DROPOFF

            elif task.phase == TransportTaskPhase.MOVE_TO_STAGING:
                if self.world.robots[task.robot_id].location == STAGING_WAYPOINT:
                    task.phase = TransportTaskPhase.WAIT_FOR_RESOURCE
                    continue
                return [self._create_move(task, STAGING_WAYPOINT)]

            elif task.phase == TransportTaskPhase.WAIT_FOR_RESOURCE:
                waiting_purpose = task.waiting_purpose
                if (
                    task.waiting_resource_id is None
                    or waiting_purpose is None
                    or not self._acquire_resource(
                        task,
                        task.waiting_resource_id,
                        waiting_purpose,
                    )
                ):
                    task.status = MissionTaskStatus.BLOCKED
                    self.world.mark_robot_waiting(task.robot_id, task.task_id)
                    return []
                task.waiting_resource_id = None
                task.waiting_purpose = None
                task.status = MissionTaskStatus.RUNNING
                task.phase = (
                    TransportTaskPhase.MOVE_TO_PICKUP
                    if waiting_purpose == "pickup"
                    else TransportTaskPhase.MOVE_TO_DROPOFF
                )

            elif task.phase == TransportTaskPhase.MOVE_TO_DROPOFF:
                if self.world.robots[task.robot_id].location == task.dropoff:
                    task.phase = TransportTaskPhase.UNLOAD_ITEM
                    continue
                return [self._create_move(task, task.dropoff)]

            elif task.phase == TransportTaskPhase.UNLOAD_ITEM:
                return [self._create_handling(task, "unload")]

            else:
                return []

        return []

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
            if task.phase == TransportTaskPhase.MOVE_TO_STAGING:
                task.phase = TransportTaskPhase.WAIT_FOR_RESOURCE
            elif task.phase == TransportTaskPhase.MOVE_TO_PICKUP:
                task.phase = TransportTaskPhase.LOAD_ITEM
            elif task.phase == TransportTaskPhase.MOVE_TO_DROPOFF:
                task.phase = TransportTaskPhase.UNLOAD_ITEM

        elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
            if command.handling_type == "load" and command.item_id is not None:
                self.world.load_item(command.robot_id, command.item_id)
                if self._resource_exists(task.pickup):
                    self.world.release_item(task.pickup, task.item_id)
                    self.world.release_resource(task.pickup, command.robot_id)
                task.phase = TransportTaskPhase.ACQUIRE_DROPOFF

            elif command.handling_type == "unload" and command.item_id is not None:
                self.world.unload_item(command.robot_id, command.item_id, task.dropoff)
                if self._resource_exists(task.dropoff):
                    self.world.buffer_item(task.dropoff, task.item_id)
                    self.world.release_resource(task.dropoff, command.robot_id)
                self.world.release_robot(command.robot_id)
                task.phase = TransportTaskPhase.DONE
                task.status = MissionTaskStatus.SUCCEEDED

        return self.advance(task)

    def _create_move(self, task: TransportItemTask, target: str) -> ExecutionCommand:
        task.status = MissionTaskStatus.RUNNING
        command = self.execution.create_move(task.task_id, task.robot_id, target)
        task.active_command_id = command.command_id
        return command

    def _create_handling(
        self,
        task: TransportItemTask,
        handling_type: str,
    ) -> ExecutionCommand:
        task.status = MissionTaskStatus.RUNNING
        command = self.execution.create_handling(
            task.task_id,
            task.robot_id,
            task.item_id,
            handling_type,
        )
        task.active_command_id = command.command_id
        return command

    def _resource_exists(self, resource_id: str) -> bool:
        return resource_id in self.world.resources

    def _acquire_resource(
        self,
        task: TransportItemTask,
        resource_id: str,
        purpose: str,
    ) -> bool:
        if task.robot_id is None:
            return False
        if not self.world.can_acquire(resource_id, task.robot_id, purpose, task.item_id):
            return False
        self.world.occupy_resource(resource_id, task.robot_id)
        return True

    def _stage_or_wait(
        self,
        task: TransportItemTask,
        resource_id: str,
        purpose: str,
    ) -> list[ExecutionCommand]:
        task.waiting_resource_id = resource_id
        task.waiting_purpose = purpose
        task.status = MissionTaskStatus.BLOCKED
        if task.robot_id is not None and self.world.robots[task.robot_id].location != STAGING_WAYPOINT:
            task.phase = TransportTaskPhase.MOVE_TO_STAGING
            task.status = MissionTaskStatus.RUNNING
            return [self._create_move(task, STAGING_WAYPOINT)]
        task.phase = TransportTaskPhase.WAIT_FOR_RESOURCE
        if task.robot_id is not None:
            self.world.mark_robot_waiting(task.robot_id, task.task_id)
        return []
