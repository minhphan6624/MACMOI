from .mission_state import TransferZoneState
from .resources import ResourceReservation, ResourceState


class WorldResourceManager:
    def __init__(
        self,
        resources: dict[str, ResourceState],
        transfer: TransferZoneState | None = None,
        transfer_resource_id: str = "transfer",
    ):
        self.resources = resources
        self.transfer = transfer
        self.transfer_resource_id = transfer_resource_id
        self._sync_transfer_resource_from_state()

    def can_acquire(
        self,
        resource_id: str,
        actor_id: str,
        purpose: str,
        item_id: str | None = None,
    ) -> bool:
        resource = self.resources[resource_id]
        if resource.robot_slots_available <= 0:
            return False
        if purpose == "dropoff":
            return item_id is not None and resource.package_slots_available > 0
        if purpose == "pickup":
            return len(resource.package_occupancy) > 0
        return True

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
        self._sync_transfer_state_from_resource()

    def release(self, resource_id: str, actor_id: str) -> None:
        resource = self.resources[resource_id]
        if actor_id in resource.robot_occupancy:
            resource.robot_occupancy.remove(actor_id)
        self._sync_transfer_state_from_resource()

    def buffer_item(self, resource_id: str, item_id: str) -> None:
        resource = self.resources[resource_id]
        if item_id not in resource.package_occupancy:
            resource.package_occupancy.append(item_id)
        self._sync_transfer_state_from_resource()

    def release_item(self, resource_id: str, item_id: str) -> None:
        resource = self.resources[resource_id]
        if item_id in resource.package_occupancy:
            resource.package_occupancy.remove(item_id)
        self._sync_transfer_state_from_resource()

    def set_waiting_actor(self, actor_id: str, item_id: str) -> None:
        if self.transfer is None:
            return
        self.transfer.waiting_robot = actor_id
        self.transfer.waiting_package = item_id

    def clear_waiting_actor(self, actor_id: str) -> None:
        if self.transfer is None:
            return
        if self.transfer.waiting_robot == actor_id:
            self.transfer.waiting_robot = None
            self.transfer.waiting_package = None

    def _sync_transfer_resource_from_state(self) -> None:
        if self.transfer is None or self.transfer_resource_id not in self.resources:
            return

        resource = self.resources[self.transfer_resource_id]
        resource.robot_occupancy = (
            [self.transfer.robot_occupancy]
            if self.transfer.robot_occupancy is not None
            else []
        )
        resource.package_occupancy = (
            [self.transfer.package_buffer]
            if self.transfer.package_buffer is not None
            else []
        )

    def _sync_transfer_state_from_resource(self) -> None:
        if self.transfer is None or self.transfer_resource_id not in self.resources:
            return

        resource = self.resources[self.transfer_resource_id]
        self.transfer.robot_occupancy = (
            resource.robot_occupancy[0] if resource.robot_occupancy else None
        )
        self.transfer.package_buffer = (
            resource.package_occupancy[0] if resource.package_occupancy else None
        )
