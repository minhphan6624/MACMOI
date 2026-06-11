from dataclasses import dataclass, field
from enum import Enum

# Classes for resource-related states/attributes 
# In this case, resources are constraint-zones

@dataclass
class ResourceLease:
    """Temporary permission for one actor to use a managed resource."""

    resource_id: str
    task_id: str
    actor_id: str
    purpose: str
    item_id: str | None = None


@dataclass
class ResourceState:
    """Mission-layer state for a constrained shared resource."""

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

# ----- Access-related classes -----
class ResourceAccessStatus(Enum):
    """Result of a request to use a managed mission resource."""

    GRANTED = "GRANTED"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"

@dataclass
class ResourceAccessDecision:
    """Resource access response with optional wait/block explanation."""

    status: ResourceAccessStatus
    target: str | None = None
    reason: str | None = None
    blocked_by: str | None = None