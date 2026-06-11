from dataclasses import dataclass, field
from enum import Enum


class ResourceAccessStatus(Enum):
    GRANTED = "GRANTED"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"


@dataclass
class ResourceLease:
    resource_id: str
    task_id: str
    actor_id: str
    purpose: str
    item_id: str | None = None


@dataclass
class ResourceAccessDecision:
    status: ResourceAccessStatus
    target: str | None = None
    reason: str | None = None
    blocked_by: str | None = None


@dataclass
class ResourceState:
    resource_id: str
    robot_capacity: int = 1
    package_capacity: int = 0
    wait_waypoint: str | None = None
    wait_waypoints: dict[str, str] = field(default_factory=dict)
    robot_occupancy: list[str] = field(default_factory=list)
    package_occupancy: list[str] = field(default_factory=list)
    active_lease: ResourceLease | None = None

    @property
    def robot_slots_available(self) -> int:
        return self.robot_capacity - len(self.robot_occupancy)

    @property
    def package_slots_available(self) -> int:
        return self.package_capacity - len(self.package_occupancy)
