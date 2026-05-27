from .actions import DispatchTask, PositionRobot, StartHandlingTimer
from .events import (
    DownstreamRobotArrivedAtStaging,
    DownstreamLegCompleted,
    DownstreamPickupCompleted,
    HandlingTimerCompleted,
    MissionStarted,
    OperatorAborted,
    OperatorPaused,
    OperatorResumed,
    RobotArrivedAtStaging,
    RobotBecameIdle,
    UpstreamLegCompleted,
)
from .mission_definition import DOWNSTREAM_ROBOT, UPSTREAM_ROBOT
from .mission_state import (
    MissionState,
    MissionStatus,
    PackageRecord,
    PackageStatus,
    RobotLocation,
    RobotMissionState,
    RobotStatus,
    TaskSegment,
    TransferZoneState,
)
from .rule_evaluator import evaluate_rules
from .transfer_controller import TransferController


class MissionManager:
    def __init__(self, state: MissionState):
        self.state = state

    @classmethod
    def create(
        cls,
        mission_id: str,
        total_packages: int,
        upstream_robot: str = UPSTREAM_ROBOT,
        downstream_robot: str = DOWNSTREAM_ROBOT,
    ):
        packages = {
            f"P{i}": PackageRecord(package_id=f"P{i}")
            for i in range(1, total_packages + 1)
        }
        state = MissionState(
            mission_id=mission_id,
            status=MissionStatus.READY,
            total_packages=total_packages,
            delivered_count=0,
            upstream_robot_id=upstream_robot,
            downstream_robot_id=downstream_robot,
            packages=packages,
            transfer=TransferZoneState(),
            robots={
                upstream_robot: RobotMissionState(
                    robot_id=upstream_robot,
                    location=RobotLocation.SOURCE,
                ),
                downstream_robot: RobotMissionState(robot_id=downstream_robot),
            },
        )
        return cls(state)
    
    def record_dispatch(self, action: DispatchTask, task_id: str) -> None:
        '''
            Mark an emitted DispatchTask as actually accepted/started by the lower layer
            THis happens after the brdige successfully submit an RMF task and return the RMF task ID
            THis Task ID is then attributed to a specific package
        '''

        # find the robot and package
        robot = self.state.robots[action.robot_id]
        package = self.state.packages[action.package_id]

        # Mark the robot as busy with that accepted task
        robot.active_task_id = task_id
        robot.active_package_id = action.package_id
        robot.status = RobotStatus.MOVING

        # Record the task ID on the package side, depending on the dispatched mission segment
        if action.robot_id == self.state.upstream_robot_id and action.segment in (
            TaskSegment.SOURCE_TO_TRANSFER,
            TaskSegment.SOURCE_TO_STAGING,
            TaskSegment.STAGING_TO_TRANSFER,
        ):
            package.upstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_TRANSFER
        
        elif action.robot_id == self.state.downstream_robot_id and action.segment in (
            TaskSegment.HOME_TO_TRANSFER,
            TaskSegment.DESTINATION_TO_TRANSFER,
            TaskSegment.STAGING_TO_TRANSFER,
        ):
            package.downstream_task_id = task_id
        
        elif action.segment == TaskSegment.TRANSFER_TO_DESTINATION:
            package.downstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_DESTINATION

    def record_position_dispatch(self, action: PositionRobot, task_id: str) -> None:
        robot = self.state.robots[action.robot_id]
        robot.active_task_id = task_id
        robot.active_package_id = None
        robot.status = RobotStatus.RETURNING

    def handle_event(self, event):
        ''' Main entrypoint to handle events'''
        actions = self._update_state(event)
        if actions:
            return actions
        return evaluate_rules(self.state)

    def _update_state(self, event):
        ''' Update the state based on the event received'''
        if getattr(event, "mission_id") != self.state.mission_id:
            return []

        handlers = {
            MissionStarted: self._handle_mission_started,
            OperatorPaused: self._handle_operator_paused,
            OperatorResumed: self._handle_operator_resumed,
            OperatorAborted: self._handle_operator_aborted,
            RobotBecameIdle: self._handle_robot_became_idle,
            RobotArrivedAtStaging: self._handle_upstream_arrived_at_staging,
            DownstreamRobotArrivedAtStaging: self._handle_downstream_arrived_at_staging,
            UpstreamLegCompleted: self._handle_upstream_leg_completed,
            DownstreamPickupCompleted: self._handle_downstream_pickup_completed,
            DownstreamLegCompleted: self._handle_downstream_leg_completed,
            HandlingTimerCompleted: self._handle_handling_timer_completed,
        }
        handler = handlers.get(type(event))
        if handler is None:
            return []

        return handler(event) or []

    # ==================== Event handlers ====================
    def _handle_mission_started(self, event: MissionStarted) -> None:
        if self.state.status == MissionStatus.READY:
            self.state.status = MissionStatus.RUNNING

    def _handle_operator_paused(self, event: OperatorPaused) -> None:
        if self.state.status == MissionStatus.RUNNING:
            self.state.status = MissionStatus.PAUSED

    def _handle_operator_resumed(self, event: OperatorResumed) -> None:
        if self.state.status == MissionStatus.PAUSED:
            self.state.status = MissionStatus.RUNNING

    def _handle_operator_aborted(self, event: OperatorAborted) -> None:
        if self.state.status not in (
            MissionStatus.COMPLETED,
            MissionStatus.ABORTED,
        ):
            self.state.status = MissionStatus.ABORTED

    def _handle_robot_became_idle(self, event: RobotBecameIdle) -> None:
        self._set_robot_idle(event.robot_id)

    def _handle_upstream_arrived_at_staging(self, event: RobotArrivedAtStaging) -> None:
        
        # FInd robot_id and package_id 
        robot = self.state.robots[event.robot_id]
        package = self.state.packages[event.package_id]
        if robot.active_task_id not in (None, event.task_id):
            return

        # Update Package details
        package.upstream_task_id = None
        package.status = PackageStatus.INBOUND_TO_TRANSFER
        
        # Update robot details
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.WAITING_AT_STAGING
        robot.location = RobotLocation.STAGING
        
        # Set the zone to be occupied by that robot
        TransferController(
            self.state.transfer,
            self.state.upstream_robot_id,
            self.state.downstream_robot_id,
        ).set_waiting_robot(
            event.robot_id,
            event.package_id,
        )

    def _handle_upstream_leg_completed(self, event: UpstreamLegCompleted):
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.AT_TRANSFER:
            return []

        package.upstream_task_id = None

        robot = self.state.robots[event.robot_id]
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.UNLOADING
        robot.location = RobotLocation.TRANSFER

        return [
            StartHandlingTimer(event.robot_id, event.package_id, "transfer_unload")
        ]
    
    def _handle_downstream_arrived_at_staging( self, event: DownstreamRobotArrivedAtStaging) -> None:
        robot = self.state.robots[event.robot_id]
        if robot.active_task_id not in (None, event.task_id):
            return
        robot.active_task_id = None
        robot.active_package_id = None
        robot.status = RobotStatus.WAITING_AT_STAGING
        robot.location = RobotLocation.STAGING

    def _handle_downstream_pickup_completed(self, event: DownstreamPickupCompleted):
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return []

        package.downstream_task_id = None

        robot = self.state.robots[event.robot_id]
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.LOADING
        robot.location = RobotLocation.TRANSFER

        return [
            StartHandlingTimer(event.robot_id, event.package_id, "transfer_load")
        ]

    def _handle_downstream_leg_completed(self, event: DownstreamLegCompleted):
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return []

        package.downstream_task_id = None

        robot = self.state.robots[event.robot_id]
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.UNLOADING
        robot.location = RobotLocation.DESTINATION

        return [
            StartHandlingTimer(event.robot_id, event.package_id, "destination_unload")
        ]

    def _handle_handling_timer_completed(self, event: HandlingTimerCompleted) -> None:
        if event.handling_type == "source_load":
            robot = self.state.robots[event.robot_id]
            robot.status = RobotStatus.IDLE
            robot.active_package_id = event.package_id
            robot.location = RobotLocation.SOURCE
            return

        if event.handling_type == "transfer_unload":
            package = self.state.packages[event.package_id]
            package.status = PackageStatus.AT_TRANSFER
            transfer = TransferController(
                self.state.transfer,
                self.state.upstream_robot_id,
                self.state.downstream_robot_id,
            )
            transfer.buffer_package(event.package_id)
            transfer.release_transfer(event.robot_id)
            self._set_robot_idle(event.robot_id)
            self.state.robots[event.robot_id].location = RobotLocation.TRANSFER
            return

        if event.handling_type == "transfer_load":
            package = self.state.packages[event.package_id]
            package.status = PackageStatus.INBOUND_TO_DESTINATION
            transfer = TransferController(
                self.state.transfer,
                self.state.upstream_robot_id,
                self.state.downstream_robot_id,
            )
            transfer.release_package(event.package_id)
            transfer.release_transfer(event.robot_id)
            robot = self.state.robots[event.robot_id]
            robot.status = RobotStatus.IDLE
            robot.active_task_id = None
            robot.active_package_id = event.package_id
            robot.location = RobotLocation.TRANSFER
            return

        if event.handling_type == "destination_unload":
            package = self.state.packages[event.package_id]
            if package.status != PackageStatus.DELIVERED:
                package.status = PackageStatus.DELIVERED
                self.state.delivered_count += 1
            self._set_robot_idle(event.robot_id)
            self.state.robots[event.robot_id].location = RobotLocation.DESTINATION

    def _set_robot_idle(self, robot_id: str) -> None:
        robot = self.state.robots[robot_id]
        robot.status = RobotStatus.IDLE
        robot.active_task_id = None
        robot.active_package_id = None
