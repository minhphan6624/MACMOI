from dataclasses import dataclass, field
from enum import Enum


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
    MOVE_TO_WAIT_POINT = "MOVE_TO_WAIT_POINT"
    MOVE_TO_TRANSFER_EXIT = "MOVE_TO_TRANSFER_EXIT"
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
    phase: TransportTaskPhase = TransportTaskPhase.NOT_STARTED
    active_command_id: str | None = None
    waiting_resource_id: str | None = None
    waiting_purpose: str | None = None
    blocked_reason: str | None = None
    blocked_by: str | None = None
    waiting_at: str | None = None
    unblock_condition: str | None = None
    next_expected_event: str | None = None
    bt_blackboard: dict = field(default_factory=dict)
