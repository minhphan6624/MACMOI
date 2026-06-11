from dataclasses import dataclass, field
from enum import Enum

from .execution import ExecutionCommand, ExecutionManager
from .mission_tasks import TransportItemTask
from .world import RuntimeWorld


class BtStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RUNNING = "RUNNING"


@dataclass
class BtResult:
    status: BtStatus
    commands: list[ExecutionCommand] = field(default_factory=list)


@dataclass
class TransportTaskContext:
    task: TransportItemTask
    world: RuntimeWorld
    execution: ExecutionManager


class BtNode:
    def tick(self, ctx: TransportTaskContext) -> BtResult:
        raise NotImplementedError


class MemorySequence(BtNode):
    def __init__(self, node_id: str, children: list[BtNode]):
        self.node_id = node_id
        self.children = children

    def tick(self, ctx: TransportTaskContext) -> BtResult:
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


class Fallback(BtNode):
    def __init__(self, children: list[BtNode]):
        self.children = children

    def tick(self, ctx: TransportTaskContext) -> BtResult:
        for child in self.children:
            result = child.tick(ctx)
            if result.status != BtStatus.FAILURE:
                return result
        return BtResult(BtStatus.FAILURE)
