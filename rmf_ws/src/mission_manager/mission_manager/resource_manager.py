from .resources import (
    ResourceAccessDecision,
    ResourceAccessStatus,
    ResourceBlockReason,
    ResourceLease,
    ResourceState,
)


class ResourceManager:
    """Applies access, lease, occupancy, and package-buffer rules."""

    def __init__(self, resources: dict[str, ResourceState]):
        self.resources = resources

    def request_access(
        self,
        resource_id: str,
        actor_id: str,
        purpose: str,
        task_id: str,
        item_id: str | None = None,
    ) -> ResourceAccessDecision:
        """Grant, wait, or block access to a managed mission resource."""

        resource = self.resources[resource_id]

        def wait(reason: str, blocked_by: str | None = None) -> ResourceAccessDecision:
            wait_waypoint = self._wait_waypoint(resource, actor_id)
            status = (
                ResourceAccessStatus.WAIT
                if wait_waypoint is not None
                else ResourceAccessStatus.BLOCKED
            )
            return ResourceAccessDecision(status, wait_waypoint, reason, blocked_by)

        if (
            resource.active_lease is not None
            and resource.active_lease.actor_id != actor_id
        ):
            return wait(
                ResourceBlockReason.WAITING_FOR_TRANSFER_LEASE,
                resource.active_lease.actor_id,
            )
        if actor_id in resource.robot_occupancy:
            return ResourceAccessDecision(ResourceAccessStatus.GRANTED)
        if resource.robot_slots_available <= 0:
            blocked_by = resource.robot_occupancy[0] if resource.robot_occupancy else None
            return wait(ResourceBlockReason.TRANSFER_ROBOT_OCCUPIED, blocked_by)

        if purpose == "dropoff":
            if item_id is None:
                return ResourceAccessDecision(
                    ResourceAccessStatus.BLOCKED,
                    reason=ResourceBlockReason.MISSING_ITEM,
                )
            if resource.package_slots_available <= 0:
                blocked_by = (
                    resource.package_occupancy[0]
                    if resource.package_occupancy
                    else None
                )
                return wait(ResourceBlockReason.TRANSFER_PACKAGE_FULL, blocked_by)
        elif purpose == "pickup" and (
            item_id is None or item_id not in resource.package_occupancy
        ):
            return wait(ResourceBlockReason.PACKAGE_NOT_AVAILABLE, item_id)

        self._grant_lease(resource, actor_id, purpose, item_id, task_id)
        return ResourceAccessDecision(ResourceAccessStatus.GRANTED)

    def _wait_waypoint(self, resource: ResourceState, actor_id: str) -> str | None:
        return resource.wait_waypoints.get(actor_id) or resource.wait_waypoint

    def _grant_lease(
        self,
        resource: ResourceState,
        actor_id: str,
        purpose: str,
        item_id: str | None,
        task_id: str,
    ) -> None:
        if resource.active_lease is not None:
            return
        resource.active_lease = ResourceLease(
            resource_id=resource.resource_id,
            task_id=task_id,
            actor_id=actor_id,
            purpose=purpose,
            item_id=item_id,
        )

    def occupy(self, resource_id: str, actor_id: str) -> None:
        resource = self.resources[resource_id]
        if actor_id not in resource.robot_occupancy:
            resource.robot_occupancy.append(actor_id)

    def release(self, resource_id: str, actor_id: str) -> None:
        resource = self.resources[resource_id]
        if actor_id in resource.robot_occupancy:
            resource.robot_occupancy.remove(actor_id)
        if resource.active_lease is not None and resource.active_lease.actor_id == actor_id:
            resource.active_lease = None

    def buffer_item(self, resource_id: str, item_id: str) -> None:
        resource = self.resources[resource_id]
        if item_id not in resource.package_occupancy:
            resource.package_occupancy.append(item_id)

    def release_item(self, resource_id: str, item_id: str) -> None:
        resource = self.resources[resource_id]
        if item_id in resource.package_occupancy:
            resource.package_occupancy.remove(item_id)
