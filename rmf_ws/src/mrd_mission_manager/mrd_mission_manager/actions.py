from dataclasses import dataclass

from .mission_state import TaskSegment


@dataclass(frozen=True)
class DispatchTask:
    robot_id: str
    package_id: str
    segment: TaskSegment


@dataclass(frozen=True)
class SendRobotHome:
    robot_id: str


@dataclass(frozen=True)
class CompleteMission:
    pass
