from dataclasses import dataclass, field
from enum import Enum

from .execution import ExecutionCommand, ExecutionManager
from .mission_tasks import TransportItemTask
from .world import MissionWorld


class BtStatus(Enum):
    """Behavior-tree tick result status."""

    SUCCESS = "SUCCESS"
    RUNNING = "RUNNING"


@dataclass
class BtResult:
    """Result of ticking a behavior-tree node."""

    status: BtStatus
    commands: list[ExecutionCommand] = field(default_factory=list)


@dataclass
class TransportTaskContext:
    """Shared context passed to transport-task behavior-tree nodes."""

    task: TransportItemTask
    world: MissionWorld
    execution: ExecutionManager


class BtNode:
    """Base class for behavior-tree nodes."""

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        raise NotImplementedError


class MemorySequence(BtNode):
    """Sequence node that resumes from the last running child."""

    def __init__(self, node_id: str, children: list[BtNode]):
        self.node_id = node_id
        self.children = children

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        """Tick children in order, resuming from the last unfinished child."""

        index_key = f"{self.node_id}.index"
        index = int(ctx.task.bt_blackboard.get(index_key, 0))

        while index < len(self.children):
            result = self.children[index].tick(ctx)
            if result.status == BtStatus.SUCCESS:
                index += 1
                ctx.task.bt_blackboard[index_key] = index
                continue
            return result

        return BtResult(BtStatus.SUCCESS)
