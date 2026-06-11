from .resources import (
    ResourceAccessDecision,
    ResourceAccessStatus,
    ResourceLease,
    ResourceReservation,
    ResourceState,
)


class WorldResourceManager:
    def __init__(
        self,
        resources: dict[str, ResourceState],
        transfer_resource_id: str = "transfer",
    ):
        self.resources = resources
        self.transfer_resource_id = transfer_resource_id

    def can_acquire(
        self,
        resource_id: str,
        actor_id: str,
        purpose: str,
        item_id: str | None = None,
    ) -> bool:
        return self.request_access(resource_id, actor_id, purpose, item_id).status == (
            ResourceAccessStatus.GRANTED
        )

    def request_access(
        self,
        resource_id: str,
        actor_id: str,
        purpose: str,
        item_id: str | None = None,
        task_id: str | None = None,
    ) -> ResourceAccessDecision:
        resource = self.resources[resource_id]

        def wait(reason: str, blocked_by: str | None = None) -> ResourceAccessDecision:
            if resource.wait_waypoint is not None:
                return ResourceAccessDecision(
                    ResourceAccessStatus.WAIT,
                    resource.wait_waypoint,
                    reason,
                    blocked_by,
                )
            return ResourceAccessDecision(
                ResourceAccessStatus.BLOCKED,
                reason=reason,
                blocked_by=blocked_by,
            )

        if (
            resource.active_lease is not None
            and resource.active_lease.actor_id != actor_id
        ):
            return wait(
                "WAITING_FOR_TRANSFER_LEASE",
                resource.active_lease.actor_id,
            )
        if actor_id in resource.robot_occupancy:
            return ResourceAccessDecision(ResourceAccessStatus.GRANTED, resource_id)
        if resource.robot_slots_available <= 0:
            blocked_by = resource.robot_occupancy[0] if resource.robot_occupancy else None
            return wait("TRANSFER_ROBOT_OCCUPIED", blocked_by)
        if purpose == "dropoff":
            if item_id is None:
                return ResourceAccessDecision(ResourceAccessStatus.BLOCKED, reason="missing_item")
            if resource.package_slots_available <= 0:
                blocked_by = resource.package_occupancy[0] if resource.package_occupancy else None
                return wait("TRANSFER_PACKAGE_FULL", blocked_by)
            self._grant_lease(resource, actor_id, purpose, item_id, task_id)
            return ResourceAccessDecision(ResourceAccessStatus.GRANTED, resource_id)
        if purpose == "pickup":
            if item_id is not None and item_id in resource.package_occupancy:
                self._grant_lease(resource, actor_id, purpose, item_id, task_id)
                return ResourceAccessDecision(ResourceAccessStatus.GRANTED, resource_id)
            return wait("PACKAGE_NOT_AVAILABLE", item_id)
        self._grant_lease(resource, actor_id, purpose, item_id, task_id)
        return ResourceAccessDecision(ResourceAccessStatus.GRANTED, resource_id)

    def _grant_lease(
        self,
        resource: ResourceState,
        actor_id: str,
        purpose: str,
        item_id: str | None,
        task_id: str | None,
    ) -> None:
        if resource.active_lease is not None:
            return
        resource.active_lease = ResourceLease(
            resource_id=resource.resource_id,
            task_id=task_id or "",
            actor_id=actor_id,
            purpose=purpose,
            item_id=item_id,
        )

    def reserve(
        self,
        resource_id: str,
        reservation_id: str,
        owner_id: str,
        actor_id: str,
        purpose: str,
        item_id: str | None = None,
    ) -> ResourceReservation:
        reservation = ResourceReservation(
            reservation_id=reservation_id,
            resource_id=resource_id,
            owner_id=owner_id,
            actor_id=actor_id,
            purpose=purpose,
            item_id=item_id,
        )
        self.resources[resource_id].reservations[reservation_id] = reservation
        
        return reservation

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

    def set_waiting_actor(self, actor_id: str, item_id: str) -> None:
        return

    def clear_waiting_actor(self, actor_id: str) -> None:
        return
