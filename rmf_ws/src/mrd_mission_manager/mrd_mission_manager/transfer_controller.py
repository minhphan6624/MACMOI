from .mission_state import DOWNSTREAM_ROBOT
from .mission_state import TransferZoneState
from .mission_state import UPSTREAM_ROBOT


class TransferController:
    def __init__(self, transfer: TransferZoneState):
        self.transfer = transfer

    def can_robot_enter(self, robot_id: str, package_id: str | None = None) -> bool:
        if self.transfer.robot_occupancy is not None:
            return False
        if robot_id == UPSTREAM_ROBOT:
            return self.transfer.package_buffer is None and package_id is not None
        if robot_id == DOWNSTREAM_ROBOT:
            return self.transfer.package_buffer is not None
        return False

    def occupy_transfer(self, robot_id: str) -> None:
        self.transfer.robot_occupancy = robot_id

    def release_transfer(self, robot_id: str) -> None:
        if self.transfer.robot_occupancy == robot_id:
            self.transfer.robot_occupancy = None

    def buffer_package(self, package_id: str) -> None:
        self.transfer.package_buffer = package_id

    def release_package(self, package_id: str) -> None:
        if self.transfer.package_buffer == package_id:
            self.transfer.package_buffer = None

    def set_waiting_robot(self, robot_id: str, package_id: str) -> None:
        self.transfer.waiting_robot = robot_id
        self.transfer.waiting_package = package_id

    def clear_waiting_robot(self, robot_id: str) -> None:
        if self.transfer.waiting_robot == robot_id:
            self.transfer.waiting_robot = None
            self.transfer.waiting_package = None
