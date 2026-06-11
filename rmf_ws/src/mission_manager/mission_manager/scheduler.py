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
            if not world.is_item_at(task.item_id, task.pickup):
                continue
            if not self._managed_pickup_available(task, world):
                continue
            return task
        return None

    def _managed_pickup_available(
        self,
        task: TransportItemTask,
        world: RuntimeWorld,
    ) -> bool:
        resource = world.resources.get(task.pickup)
        if resource is None:
            return True
        return (
            resource.active_lease is None
            and resource.robot_slots_available > 0
            and task.item_id in resource.package_occupancy
        )
