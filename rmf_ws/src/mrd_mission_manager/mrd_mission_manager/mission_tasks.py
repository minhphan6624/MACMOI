from dataclasses import dataclass, field
from enum import Enum


class MissionTaskType(Enum):
    TRANSPORT_ITEM = "transport_item"


class MissionTaskStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class TransportItemTask:
    task_id: str
    item_id: str
    pickup: str
    dropoff: str
    robot_id: str | None = None
    status: MissionTaskStatus = MissionTaskStatus.PENDING
    task_type: MissionTaskType = MissionTaskType.TRANSPORT_ITEM
    required_resources: list[str] = field(default_factory=list)
