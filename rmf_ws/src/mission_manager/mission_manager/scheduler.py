from .mission_tasks import MissionTaskStatus, TransportItemTask
from .world import MissionWorld


class TransportTaskScheduler:
    """Selects the next pending transport task that can make progress."""

    def next_ready_task( self, tasks: dict[str, TransportItemTask], 
                        world: MissionWorld,) -> TransportItemTask | None:
        """Return the first pending task whose robot, package, and pickup are ready."""

        for task_id in sorted(tasks):
            task = tasks[task_id]

            if task.status != MissionTaskStatus.PENDING:
                continue

            if not world.is_robot_available(task.robot_id):
                continue
            item_at_pickup = world.is_item_at(task.item_id, task.pickup)

            if not item_at_pickup and not self._can_wait_for_pickup(task, world):
                continue
            if item_at_pickup and not self._managed_pickup_available(task, world):
                continue
            return task
        return None

    def _can_wait_for_pickup(self, task: TransportItemTask, world: MissionWorld,) -> bool:
        """Return whether the robot can pre-stage while waiting for pickup."""

        resource = world.resources.get(task.pickup)
        item = world.items.get(task.item_id)

        return (
            resource is not None
            and (
                resource.wait_waypoint is not None
                or task.robot_id in resource.wait_waypoints
            )
            and item is not None
            and item.carried_by is not None
        )

    def _managed_pickup_available(self, task: TransportItemTask, world: MissionWorld,) -> bool:
        """Return whether a managed pickup resource is ready for this task."""

        resource = world.resources.get(task.pickup)
        if resource is None:
            return True

        return (
            resource.active_lease is None
            and resource.robot_slots_available > 0
            and task.item_id in resource.package_occupancy
        )
