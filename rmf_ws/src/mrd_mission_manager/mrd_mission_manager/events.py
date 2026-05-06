from dataclasses import dataclass


@dataclass(frozen=True)
class MissionStarted:
    mission_id: str


@dataclass(frozen=True)
class RobotBecameIdle:
    mission_id: str
    robot_id: str


@dataclass(frozen=True)
class RobotArrivedAtStaging:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str


@dataclass(frozen=True)
class DownstreamRobotArrivedAtStaging:
    mission_id: str
    robot_id: str
    task_id: str


@dataclass(frozen=True)
class UpstreamLegCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str


@dataclass(frozen=True)
class DownstreamPickupCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str


@dataclass(frozen=True)
class DownstreamLegCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str


@dataclass(frozen=True)
class HandlingTimerCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    handling_type: str


@dataclass(frozen=True)
class OperatorPaused:
    mission_id: str


@dataclass(frozen=True)
class OperatorResumed:
    mission_id: str


@dataclass(frozen=True)
class OperatorAborted:
    mission_id: str
