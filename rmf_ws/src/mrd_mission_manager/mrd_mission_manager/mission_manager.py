from .actions import DispatchTask
from .events import DownstreamLegCompleted
from .events import DownstreamPickupCompleted
from .events import MissionStarted
from .events import OperatorAborted
from .events import OperatorPaused
from .events import OperatorResumed
from .events import RobotArrivedAtStaging
from .events import RobotBecameIdle
from .events import UpstreamLegCompleted
from .mission_state import MissionState
from .mission_state import MissionStatus
from .mission_state import PackageStatus
from .mission_state import RobotStatus
from .mission_state import TaskSegment
from .mission_state import create_mission
from .rule_evaluator import evaluate_rules
from .transfer_controller import TransferController


class MissionManager:
    def __init__(self, state: MissionState):
        self.state = state

    @classmethod
    def create(cls, mission_id: str, total_packages: int):
        return cls(create_mission(mission_id, total_packages))

    def handle_event(self, event):
        self._update_state(event)
        return evaluate_rules(self.state)

    def record_dispatch(self, action: DispatchTask, task_id: str) -> None:
        robot = self.state.robots[action.robot_id]
        package = self.state.packages[action.package_id]

        robot.active_task_id = task_id
        robot.active_package_id = action.package_id
        robot.status = RobotStatus.MOVING

        if action.segment in (
            TaskSegment.SOURCE_TO_STAGING,
            TaskSegment.STAGING_TO_TRANSFER,
        ):
            package.upstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_TRANSFER
        elif action.segment == TaskSegment.HOME_TO_TRANSFER:
            package.downstream_task_id = task_id
        elif action.segment == TaskSegment.TRANSFER_TO_DESTINATION:
            package.downstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_DESTINATION

    def _update_state(self, event) -> None:
        if getattr(event, "mission_id", self.state.mission_id) != self.state.mission_id:
            return

        if isinstance(event, MissionStarted):
            if self.state.status == MissionStatus.READY:
                self.state.status = MissionStatus.RUNNING
            return

        if isinstance(event, OperatorPaused):
            if self.state.status == MissionStatus.RUNNING:
                self.state.status = MissionStatus.PAUSED
            return

        if isinstance(event, OperatorResumed):
            if self.state.status == MissionStatus.PAUSED:
                self.state.status = MissionStatus.RUNNING
            return

        if isinstance(event, OperatorAborted):
            if self.state.status not in (
                MissionStatus.COMPLETED,
                MissionStatus.ABORTED,
            ):
                self.state.status = MissionStatus.ABORTED
            return

        if isinstance(event, RobotBecameIdle):
            self._set_robot_idle(event.robot_id)
            return

        if isinstance(event, RobotArrivedAtStaging):
            self._handle_arrived_at_staging(event)
            return

        if isinstance(event, UpstreamLegCompleted):
            self._handle_upstream_leg_completed(event)
            return

        if isinstance(event, DownstreamPickupCompleted):
            self._handle_downstream_pickup_completed(event)
            return

        if isinstance(event, DownstreamLegCompleted):
            self._handle_downstream_leg_completed(event)

    def _handle_arrived_at_staging(self, event: RobotArrivedAtStaging) -> None:
        robot = self.state.robots[event.robot_id]
        package = self.state.packages[event.package_id]
        if robot.active_task_id not in (None, event.task_id):
            return

        package.upstream_task_id = None
        package.status = PackageStatus.INBOUND_TO_TRANSFER
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.WAITING_AT_STAGING
        TransferController(self.state.transfer).set_waiting_robot(
            event.robot_id,
            event.package_id,
        )

    def _handle_upstream_leg_completed(self, event: UpstreamLegCompleted) -> None:
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.AT_TRANSFER:
            return

        package.upstream_task_id = None
        package.status = PackageStatus.AT_TRANSFER

        transfer = TransferController(self.state.transfer)
        transfer.buffer_package(event.package_id)
        transfer.release_transfer(event.robot_id)
        self._set_robot_idle(event.robot_id)

    def _handle_downstream_pickup_completed(
        self,
        event: DownstreamPickupCompleted,
    ) -> None:
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return

        package.downstream_task_id = None
        package.status = PackageStatus.INBOUND_TO_DESTINATION

        transfer = TransferController(self.state.transfer)
        transfer.release_package(event.package_id)
        transfer.release_transfer(event.robot_id)

        robot = self.state.robots[event.robot_id]
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.IDLE

    def _handle_downstream_leg_completed(self, event: DownstreamLegCompleted) -> None:
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return

        package.downstream_task_id = None
        package.status = PackageStatus.DELIVERED
        self.state.delivered_count += 1
        self._set_robot_idle(event.robot_id)

    def _set_robot_idle(self, robot_id: str) -> None:
        robot = self.state.robots[robot_id]
        robot.status = RobotStatus.IDLE
        robot.active_task_id = None
        robot.active_package_id = None
