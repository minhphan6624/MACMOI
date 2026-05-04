from dataclasses import dataclass
from enum import Enum


UPSTREAM_ROBOT = "tb3_1"
DOWNSTREAM_ROBOT = "tb3_2"


class MissionStatus(Enum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class PackageStatus(Enum):
    AT_SOURCE = "AT_SOURCE"
    INBOUND_TO_TRANSFER = "INBOUND_TO_TRANSFER"
    AT_TRANSFER = "AT_TRANSFER"
    INBOUND_TO_DESTINATION = "INBOUND_TO_DESTINATION"
    DELIVERED = "DELIVERED"


class RobotStatus(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    WAITING_AT_STAGING = "WAITING_AT_STAGING"
    RETURNING = "RETURNING"


class TaskSegment(Enum):
    SOURCE_TO_STAGING = "source_to_staging"
    STAGING_TO_TRANSFER = "staging_to_transfer"
    HOME_TO_TRANSFER = "home_to_transfer"
    TRANSFER_TO_DESTINATION = "transfer_to_destination"
    HOME = "home"


@dataclass
class PackageRecord:
    package_id: str
    status: PackageStatus = PackageStatus.AT_SOURCE
    upstream_task_id: str | None = None
    downstream_task_id: str | None = None


@dataclass
class TransferZoneState:
    robot_occupancy: str | None = None
    package_buffer: str | None = None
    waiting_robot: str | None = None
    waiting_package: str | None = None


@dataclass
class RobotMissionState:
    robot_id: str
    status: RobotStatus = RobotStatus.IDLE
    active_task_id: str | None = None
    active_package_id: str | None = None


@dataclass
class MissionState:
    mission_id: str
    status: MissionStatus
    total_packages: int
    delivered_count: int
    packages: dict[str, PackageRecord]
    transfer: TransferZoneState
    robots: dict[str, RobotMissionState]


def create_mission(
    mission_id: str,
    total_packages: int,
    upstream_robot: str = UPSTREAM_ROBOT,
    downstream_robot: str = DOWNSTREAM_ROBOT,
) -> MissionState:
    packages = {
        f"P{i}": PackageRecord(package_id=f"P{i}")
        for i in range(1, total_packages + 1)
    }
    return MissionState(
        mission_id=mission_id,
        status=MissionStatus.READY,
        total_packages=total_packages,
        delivered_count=0,
        packages=packages,
        transfer=TransferZoneState(),
        robots={
            upstream_robot: RobotMissionState(robot_id=upstream_robot),
            downstream_robot: RobotMissionState(robot_id=downstream_robot),
        },
    )
