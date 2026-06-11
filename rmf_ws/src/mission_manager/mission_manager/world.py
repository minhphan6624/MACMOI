from dataclasses import dataclass
from enum import Enum

from .resources import ResourceState
from .world_resource_manager import ResourceManager

# Everything state-related for components in the "world"

class RobotStatus(Enum):
    """Robot availability from the mission scheduler's point of view."""
    
    IDLE = "IDLE"
    BUSY = "BUSY"
    WAITING = "WAITING"


@dataclass
class RobotState:
    """Mission-layer robot state, not raw RMF or Nav2 telemetry."""

    robot_id: str
    location: str
    status: RobotStatus = RobotStatus.IDLE
    active_task_id: str | None = None


@dataclass
class PackageState:
    """Mission-layer package location and carrier state."""

    item_id: str
    location: str
    carried_by: str | None = None


class MissionWorld:
    """Mission-layer belief state for robots, packages, and managed resources."""

    def __init__(
        self,
        robots: dict[str, RobotState],
        items: dict[str, PackageState],
        resources: dict[str, ResourceState],
    ):
        self.robots = robots
        self.items = items
        self.resources = resources
        self.resources_manager = ResourceManager(resources)

    def is_robot_available(self, robot_id: str) -> bool:
        robot = self.robots.get(robot_id)
        return robot is not None and robot.status == RobotStatus.IDLE

    def is_item_at(self, item_id: str, location: str) -> bool:
        item = self.items.get(item_id)
        return item is not None and item.location == location and item.carried_by is None

    def assign_robot(self, robot_id: str, task_id: str) -> None:
        robot = self.robots[robot_id]
        robot.status = RobotStatus.BUSY
        robot.active_task_id = task_id

    def release_robot(self, robot_id: str) -> None:
        robot = self.robots[robot_id]
        robot.status = RobotStatus.IDLE
        robot.active_task_id = None

    def mark_robot_waiting(self, robot_id: str, task_id: str) -> None:
        robot = self.robots[robot_id]
        robot.status = RobotStatus.WAITING
        robot.active_task_id = task_id

    def move_robot(self, robot_id: str, location: str) -> None:
        self.robots[robot_id].location = location

    def load_item(self, robot_id: str, item_id: str) -> None:
        item = self.items[item_id]
        item.carried_by = robot_id
        item.location = self.robots[robot_id].location

    def unload_item(self, robot_id: str, item_id: str, location: str) -> None:
        item = self.items[item_id]
        if item.carried_by == robot_id:
            item.carried_by = None
        item.location = location
