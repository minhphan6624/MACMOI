from .mission_tasks import MissionTaskStatus, TransportItemTask
from .world import RuntimeWorld


class TransportTaskScheduler:
    def next_ready_task( self, tasks: dict[str, TransportItemTask], world: RuntimeWorld) -> TransportItemTask | None:
        for task_id in sorted(tasks):
            task = tasks[task_id]
            if task.status != MissionTaskStatus.PENDING:
                continue
            if task.robot_id is None:
                continue
            if not world.is_robot_available(task.robot_id):
                continue
            if not world.is_item_at(task.item_id, task.pickup) and not self._can_wait_for_pickup(
                task,
                world,
            ):
                continue
            return task
        return None

    def _can_wait_for_pickup(
        self,
        task: TransportItemTask,
        world: RuntimeWorld,
    ) -> bool:
        resource = world.resources.get(task.pickup)
        item = world.items.get(task.item_id)
        return (
            resource is not None
            and resource.wait_waypoint is not None
            and item is not None
            and item.carried_by is not None
        )
