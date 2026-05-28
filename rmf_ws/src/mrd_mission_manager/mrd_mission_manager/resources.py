from dataclasses import dataclass, field
from enum import Enum


class ResourceType(Enum):
    TRANSFER_ZONE = "transfer_zone"
    STAGING_ZONE = "staging_zone"
    BUFFER = "buffer"


class ResourceReservationStatus(Enum):
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


@dataclass
class ResourceReservation:
    reservation_id: str
    resource_id: str
    owner_id: str
    actor_id: str
    purpose: str
    item_id: str | None = None
    status: ResourceReservationStatus = ResourceReservationStatus.RESERVED


@dataclass
class ResourceState:
    resource_id: str
    resource_type: ResourceType
    robot_capacity: int = 1
    package_capacity: int = 0
    robot_occupancy: list[str] = field(default_factory=list)
    package_occupancy: list[str] = field(default_factory=list)
    reservations: dict[str, ResourceReservation] = field(default_factory=dict)

    @property
    def robot_slots_available(self) -> int:
        return self.robot_capacity - len(self.robot_occupancy)

    @property
    def package_slots_available(self) -> int:
        return self.package_capacity - len(self.package_occupancy)
