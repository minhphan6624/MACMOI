from .actions import CompleteMission, DispatchTask, SendRobotHome
from .mission_state import (
    MissionState,
    MissionStatus,
    PackageStatus,
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
    actions.extend(_start_upstream_package(state))
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
    
    robot = state.robots[state.downstream_robot_id] # Robot2
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
    if (robot.status != RobotStatus.IDLE
        or robot.active_task_id is not None or package.downstream_task_id is not None
        or package.status != PackageStatus.AT_TRANSFER
        or not transfer.can_robot_enter(state.downstream_robot_id, package_id)
    ):
        return []

    transfer.occupy_transfer(state.downstream_robot_id)
    return [
        DispatchTask(
            state.downstream_robot_id,
            package_id,
            TaskSegment.HOME_TO_TRANSFER,
        )
    ]


def _start_upstream_package(state: MissionState):
    robot = state.robots[state.upstream_robot_id]
    if robot.status != RobotStatus.IDLE or robot.active_task_id is not None:
        return []
    if state.transfer.package_buffer is not None:
        return []

    package = _next_package_at_source(state)
    if package is None or package.upstream_task_id is not None:
        return []

    return [
        DispatchTask(
            state.upstream_robot_id,
            package.package_id,
            TaskSegment.SOURCE_TO_STAGING,
        )
    ]


def _next_package_at_source(state: MissionState):
    for package_id in sorted(state.packages):
        package = state.packages[package_id]
        if package.status == PackageStatus.AT_SOURCE:
            return package
    return None
