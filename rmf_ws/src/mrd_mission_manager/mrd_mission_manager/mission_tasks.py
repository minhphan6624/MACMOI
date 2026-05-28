from dataclasses import dataclass, field
from enum import Enum


class MissionTaskType(Enum):
    TRANSPORT_ITEM = "transport_item"


class MissionStatus(Enum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class MissionTaskStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TransportTaskPhase(Enum):
    NOT_STARTED = "NOT_STARTED"
    ACQUIRE_PICKUP = "ACQUIRE_PICKUP"
    MOVE_TO_PICKUP = "MOVE_TO_PICKUP"
    LOAD_ITEM = "LOAD_ITEM"
    ACQUIRE_DROPOFF = "ACQUIRE_DROPOFF"
    MOVE_TO_STAGING = "MOVE_TO_STAGING"
    WAIT_FOR_RESOURCE = "WAIT_FOR_RESOURCE"
    MOVE_TO_DROPOFF = "MOVE_TO_DROPOFF"
    UNLOAD_ITEM = "UNLOAD_ITEM"
    DONE = "DONE"


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
    phase: TransportTaskPhase = TransportTaskPhase.NOT_STARTED
    active_command_id: str | None = None
    waiting_resource_id: str | None = None
    waiting_purpose: str | None = None
    bt_blackboard: dict = field(default_factory=dict)
