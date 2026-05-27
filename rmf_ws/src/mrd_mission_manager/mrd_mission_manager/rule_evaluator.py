from .actions import CompleteMission, DispatchTask, PositionRobot, SendRobotHome, StartHandlingTimer
from .mission_state import (
    MissionState,
    MissionStatus,
    PackageStatus,
    RobotLocation,
    RobotStatus,
    TaskSegment,
)
from .transfer_controller import TransferController


def evaluate_rules(state: MissionState):
    actions = []

    if state.status != MissionStatus.RUNNING:
        return []

    actions.extend(_completion_actions(state))
    if state.status != MissionStatus.RUNNING:
        return actions

    transfer = TransferController(
        state.transfer,
        state.upstream_robot_id,
        state.downstream_robot_id,
    )

    actions.extend(_continue_downstream_delivery(state))
    actions.extend(_grant_transfer_entry(state, transfer))
    actions.extend(_start_downstream_package(state, transfer))
    actions.extend(_stage_downstream_robot(state))
    actions.extend(_start_upstream_package(state, transfer))
    return actions


def _completion_actions(state: MissionState):
    if state.delivered_count != state.total_packages:
        return []

    state.status = MissionStatus.COMPLETED
    actions = [CompleteMission()]

    for robot in state.robots.values():
        if robot.status == RobotStatus.IDLE:
            actions.append(SendRobotHome(robot.robot_id))
    
    return actions


def _grant_transfer_entry(state: MissionState, transfer: TransferController):
    robot_id = state.transfer.waiting_robot
    package_id = state.transfer.waiting_package
    
    if robot_id is None or package_id is None:
        return []
    if not transfer.can_robot_enter(robot_id, package_id):
        return []

    robot = state.robots[robot_id]
    package = state.packages[package_id]
    if robot.active_task_id is not None or package.upstream_task_id is not None:
        return []

    transfer.occupy_transfer(robot_id)
    transfer.clear_waiting_robot(robot_id)
    return [
        DispatchTask(robot_id, package_id, TaskSegment.STAGING_TO_TRANSFER)
    ]


def _continue_downstream_delivery(state: MissionState):
    robot = state.robots[state.downstream_robot_id]
    package_id = robot.active_package_id
    
    if package_id is None:
        return []
    
    package = state.packages[package_id]
    
    if (
        robot.status != RobotStatus.IDLE
        or robot.active_task_id is not None
        or package.downstream_task_id is not None
        or package.status != PackageStatus.INBOUND_TO_DESTINATION
    ):
        return []

    return [
        DispatchTask(
            state.downstream_robot_id,
            package_id,
            TaskSegment.TRANSFER_TO_DESTINATION,
        )
    ]


def _start_downstream_package(state: MissionState, transfer: TransferController):
    package_id = state.transfer.package_buffer
    if package_id is None:
        return []

    robot = state.robots[state.downstream_robot_id]
    package = state.packages[package_id]
    if (robot.status not in (RobotStatus.IDLE, RobotStatus.WAITING_AT_STAGING)
        or robot.active_task_id is not None or package.downstream_task_id is not None
        or package.status != PackageStatus.AT_TRANSFER
        or not transfer.can_robot_enter(state.downstream_robot_id, package_id)
    ):
        return []

    transfer.occupy_transfer(state.downstream_robot_id)

    segment = TaskSegment.HOME_TO_TRANSFER
    if robot.location == RobotLocation.DESTINATION:
        segment = TaskSegment.DESTINATION_TO_TRANSFER
    
    elif robot.location == RobotLocation.STAGING:
        segment = TaskSegment.STAGING_TO_TRANSFER

    return [
        DispatchTask(
            state.downstream_robot_id,
            package_id,
            segment,
        )
    ]


def _stage_downstream_robot(state: MissionState):
    robot = state.robots[state.downstream_robot_id]
    if robot.status != RobotStatus.IDLE or robot.active_task_id is not None:
        return []
    if robot.active_package_id is not None:
        return []
    if state.transfer.robot_occupancy == state.downstream_robot_id:
        return []
    if (
        state.transfer.package_buffer is not None
        and state.transfer.robot_occupancy is None
    ):
        return []
    
    if robot.location == RobotLocation.STAGING:
        return []
    if state.delivered_count == state.total_packages:
        return []

    segment = TaskSegment.HOME_TO_STAGING
    if robot.location == RobotLocation.DESTINATION:
        segment = TaskSegment.DESTINATION_TO_STAGING
    return [PositionRobot(state.downstream_robot_id, segment)]


def _start_upstream_package(state: MissionState, transfer: TransferController):
    robot = state.robots[state.upstream_robot_id]
    if robot.status != RobotStatus.IDLE or robot.active_task_id is not None:
        return []
    if state.transfer.package_buffer is not None:
        return []

    if robot.active_package_id is not None:
        package = state.packages[robot.active_package_id]
        if package.upstream_task_id is not None:
            return []
        if transfer.can_robot_enter(state.upstream_robot_id, package.package_id):
            transfer.occupy_transfer(state.upstream_robot_id)
            segment = TaskSegment.SOURCE_TO_TRANSFER
        else:
            segment = TaskSegment.SOURCE_TO_STAGING
        return [
            DispatchTask(
                state.upstream_robot_id,
                package.package_id,
                segment,
            )
        ]

    package = _next_package_at_source(state)
    if package is None or package.upstream_task_id is not None:
        return []

    robot.status = RobotStatus.LOADING
    robot.active_package_id = package.package_id
    return [
        StartHandlingTimer(
            state.upstream_robot_id,
            package.package_id,
            "source_load",
        )
    ]


def _next_package_at_source(state: MissionState):
    for package_id in sorted(state.packages):
        package = state.packages[package_id]
        if package.status == PackageStatus.AT_SOURCE:
            return package
    return None
