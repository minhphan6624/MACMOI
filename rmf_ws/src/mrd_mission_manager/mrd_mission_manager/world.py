from dataclasses import dataclass
from enum import Enum

from .resources import ResourceState
from .world_resource_manager import WorldResourceManager


class WorldRobotStatus(Enum):
    IDLE = "IDLE"
    BUSY = "BUSY"
    WAITING = "WAITING"


@dataclass
class WorldRobotState:
    robot_id: str
    location: str
    status: WorldRobotStatus = WorldRobotStatus.IDLE
    active_task_id: str | None = None


@dataclass
class WorldItemState:
    item_id: str
    location: str
    carried_by: str | None = None


class RuntimeWorld:
    def __init__(
        self,
        robots: dict[str, WorldRobotState],
        items: dict[str, WorldItemState],
        resources: dict[str, ResourceState],
    ):
        self.robots = robots
        self.items = items
        self.resources = resources
        self.resources_manager = WorldResourceManager(resources)

    def is_robot_available(self, robot_id: str) -> bool:
        robot = self.robots.get(robot_id)
        return robot is not None and robot.status == WorldRobotStatus.IDLE

    def is_item_at(self, item_id: str, location: str) -> bool:
        item = self.items.get(item_id)
        return item is not None and item.location == location and item.carried_by is None

    def assign_robot(self, robot_id: str, task_id: str) -> None:
        robot = self.robots[robot_id]
        robot.status = WorldRobotStatus.BUSY
        robot.active_task_id = task_id

    def release_robot(self, robot_id: str) -> None:
        robot = self.robots[robot_id]
        robot.status = WorldRobotStatus.IDLE
        robot.active_task_id = None

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

    def can_acquire(
        self,
        resource_id: str,
        actor_id: str,
        purpose: str,
        item_id: str | None = None,
    ) -> bool:
        return self.resources_manager.can_acquire(
            resource_id,
            actor_id,
            purpose,
            item_id,
        )

    def occupy_resource(self, resource_id: str, actor_id: str) -> None:
        self.resources_manager.occupy(resource_id, actor_id)

    def release_resource(self, resource_id: str, actor_id: str) -> None:
        self.resources_manager.release(resource_id, actor_id)

    def buffer_item(self, resource_id: str, item_id: str) -> None:
        self.resources_manager.buffer_item(resource_id, item_id)

    def release_item(self, resource_id: str, item_id: str) -> None:
        self.resources_manager.release_item(resource_id, item_id)
