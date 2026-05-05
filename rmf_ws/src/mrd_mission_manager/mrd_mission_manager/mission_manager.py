from .actions import DispatchTask
from .events import (
    DownstreamLegCompleted,
    DownstreamPickupCompleted,
    MissionStarted,
    OperatorAborted,
    OperatorPaused,
    OperatorResumed,
    RobotArrivedAtStaging,
    RobotBecameIdle,
    UpstreamLegCompleted,
)
from .mission_state import (
    DOWNSTREAM_ROBOT,
    MissionState,
    MissionStatus,
    PackageRecord,
    PackageStatus,
    RobotMissionState,
    RobotStatus,
    TaskSegment,
    TransferZoneState,
    UPSTREAM_ROBOT,
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
                upstream_robot: RobotMissionState(robot_id=upstream_robot),
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
        if action.segment in (
            TaskSegment.SOURCE_TO_STAGING, TaskSegment.STAGING_TO_TRANSFER,
        ):
            package.upstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_TRANSFER
        
        elif action.segment == TaskSegment.HOME_TO_TRANSFER:
            package.downstream_task_id = task_id
        
        elif action.segment == TaskSegment.TRANSFER_TO_DESTINATION:
            package.downstream_task_id = task_id
            package.status = PackageStatus.INBOUND_TO_DESTINATION

    def handle_event(self, event):
        ''' Main entrypoint to handle events'''
        self._update_state(event)
        return evaluate_rules(self.state)

    def _update_state(self, event) -> None:
        ''' Update the state based on the event received'''
        if getattr(event, "mission_id") != self.state.mission_id:
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

    # ==================== Event handlers ====================
    def _handle_arrived_at_staging(self, event: RobotArrivedAtStaging) -> None:
        
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
        
        # Set the zone to be occupied by that robot
        TransferController(
            self.state.transfer,
            self.state.upstream_robot_id,
            self.state.downstream_robot_id,
        ).set_waiting_robot(
            event.robot_id,
            event.package_id,
        )

    def _handle_upstream_leg_completed(self, event: UpstreamLegCompleted) -> None:
        
        # UPdate package
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.AT_TRANSFER:
            return

        package.upstream_task_id = None # Clear attributed upstream RMF task 
        package.status = PackageStatus.AT_TRANSFER

        # Update transfer controller
        transfer = TransferController(
            self.state.transfer,
            self.state.upstream_robot_id,
            self.state.downstream_robot_id,
        )
        transfer.buffer_package(event.package_id) # Mark pacakge as being buffered in the zone
        transfer.release_transfer(event.robot_id) # Mark robot as being relaesed at transfer

        self._set_robot_idle(event.robot_id) 

    def _handle_downstream_pickup_completed(self, event: DownstreamPickupCompleted) -> None:
        
        # Clear downstream attached RMF task, then mark pacakge status as INBOUND_TO_DEST
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return

        package.downstream_task_id = None
        package.status = PackageStatus.INBOUND_TO_DESTINATION

        # Update Transferzone to release package + robot
        transfer = TransferController(
            self.state.transfer,
            self.state.upstream_robot_id,
            self.state.downstream_robot_id,
        )
        transfer.release_package(event.package_id)
        transfer.release_transfer(event.robot_id)

        # Attribute the said package to the robot, then make robot IDLE
        robot = self.state.robots[event.robot_id]
        robot.active_task_id = None
        robot.active_package_id = event.package_id
        robot.status = RobotStatus.IDLE

    def _handle_downstream_leg_completed(self, event: DownstreamLegCompleted) -> None:
        
        # Mark package status as completed
        package = self.state.packages[event.package_id]
        if package.status == PackageStatus.DELIVERED:
            return

        package.downstream_task_id = None
        package.status = PackageStatus.DELIVERED

        # Update delivered count and set robot to idle
        self.state.delivered_count += 1
        self._set_robot_idle(event.robot_id)

    def _set_robot_idle(self, robot_id: str) -> None:
        robot = self.state.robots[robot_id]
        robot.status = RobotStatus.IDLE
        robot.active_task_id = None
        robot.active_package_id = None