from .mission_definition import DOWNSTREAM_ROBOT, UPSTREAM_ROBOT
from .mission_state import TransferZoneState

class TransferController:
    def __init__(
        self,
        transfer: TransferZoneState,
        upstream_robot: str = UPSTREAM_ROBOT,
        downstream_robot: str = DOWNSTREAM_ROBOT,
    ):
        self.transfer = transfer
        self.upstream_robot = upstream_robot
        self.downstream_robot = downstream_robot

    def can_robot_enter(self, robot_id: str, package_id: str | None = None) -> bool:
        ''' Decide whether a robot can enter the transfer zone'''
        if self.transfer.robot_occupancy is not None:
            return False
        if robot_id == self.upstream_robot:
            return self.transfer.package_buffer is None and package_id is not None
        if robot_id == self.downstream_robot:
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
