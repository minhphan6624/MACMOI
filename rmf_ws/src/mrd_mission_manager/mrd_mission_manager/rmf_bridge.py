import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .actions import DispatchTask, PositionRobot, SendRobotHome
from .events import (
    DownstreamRobotArrivedAtStaging,
    DownstreamLegCompleted,
    DownstreamPickupCompleted,
    RobotArrivedAtStaging,
    RobotBecameIdle,
    UpstreamLegCompleted,
)
from .mission_state import DOWNSTREAM_ROBOT, UPSTREAM_ROBOT, TaskSegment


@dataclass(frozen=True)
class MissionBridgeConfig:
    fleet_name: str = "tb3_lab"
    upstream_robot: str = UPSTREAM_ROBOT
    downstream_robot: str = DOWNSTREAM_ROBOT
    source_waypoint: str = "wp1"
    staging_waypoint: str = "wp2"
    transfer_waypoint: str = "wp3"
    destination_waypoint: str = "wp4"
    upstream_home_waypoint: str = "wp1"
    downstream_home_waypoint: str = "wp2"
    requester: str = "mrd_mission_manager"


@dataclass(frozen=True)
class TaskContext:
    ''' Bridge memory of what an accepted RMF task means to the mission'''
    mission_id: str
    robot_id: str
    package_id: str | None
    segment: TaskSegment


class RmfMissionBridge:
    def __init__(
        self,
        mission_manager,
        config: MissionBridgeConfig | None = None,
        publish_request=None,
        logger=None,
    ):
        self.mission_manager = mission_manager
        self.config = config or MissionBridgeConfig()
        self.publish_request = publish_request # callback used to publish the RMF API request.
        self.logger = logger
        
        self.pending_actions: dict[str, DispatchTask | PositionRobot | SendRobotHome] = {} # maps RMF API request IDs to mission actions before RMF accept/rejects
        self.task_context_by_id: dict[str, TaskContext] = {} # maps accepted RMF task IDs to mission context
        self.completed_task_ids: set[str] = set() # prevent duplicate completion handling

    # ==================== OUTBOUND FLOW ====================
    def get_waypoints(self, robot_id: str, segment: TaskSegment) -> list[str]:
        ''' Maps task segment to actual waypoints in config'''
        if segment == TaskSegment.SOURCE_TO_TRANSFER:
            return [self.config.source_waypoint, self.config.transfer_waypoint]
        if segment == TaskSegment.SOURCE_TO_STAGING:
            return [self.config.source_waypoint, self.config.staging_waypoint]
        if segment == TaskSegment.STAGING_TO_TRANSFER:
            return [self.config.staging_waypoint, self.config.transfer_waypoint]
        if segment == TaskSegment.HOME_TO_TRANSFER:
            return [self.get_home_waypoint(robot_id), self.config.transfer_waypoint]
        if segment == TaskSegment.DESTINATION_TO_TRANSFER:
            return [self.config.destination_waypoint, self.config.transfer_waypoint]
        if segment == TaskSegment.HOME_TO_STAGING:
            return [self.get_home_waypoint(robot_id), self.config.staging_waypoint]
        if segment == TaskSegment.DESTINATION_TO_STAGING:
            return [self.config.destination_waypoint, self.config.staging_waypoint]
        if segment == TaskSegment.TRANSFER_TO_DESTINATION:
            return [self.config.transfer_waypoint, self.config.destination_waypoint]
        if segment == TaskSegment.HOME:
            return [self.get_home_waypoint(robot_id)]
        raise ValueError(f"Unsupported task segment: {segment}")

    def get_home_waypoint(self, robot_id: str) -> str:
        if robot_id == self.config.upstream_robot:
            return self.config.upstream_home_waypoint
        else:
            return self.config.downstream_home_waypoint

    def build_payload(self,action: DispatchTask | PositionRobot | SendRobotHome) -> dict[str, Any]:
        ''' 
        Build a json payload to be sent to the RMF common 
        '''

        robot_id = action.robot_id
        labels = [
            f"mission_id={self.mission_manager.state.mission_id}",
            "app=mrd_mission_manager",
        ]

        if isinstance(action, DispatchTask):
            segment = action.segment
            package_id = action.package_id
            labels.extend(
                [
                    f"package_id={package_id}",
                    f"segment={segment.value}",
                ]
            )
        elif isinstance(action, PositionRobot):
            segment = action.segment
            package_id = None
            labels.append(f"segment={segment.value}")
        else:
            segment = TaskSegment.HOME
            package_id = None
            labels.append(f"segment={segment.value}")

        return {
            "type": "robot_task_request",
            "robot": robot_id,
            "fleet": self.config.fleet_name,
            "request": {
                "category": "patrol",
                "fleet_name": self.config.fleet_name,
                "description": {
                    "places": self.get_waypoints(robot_id, segment),
                    "rounds": 1,
                },
                "labels": labels,
                "requester": self.config.requester,
            },
        }

    def submit_action( self, action: DispatchTask | PositionRobot | SendRobotHome) -> str:
        request_id = f"mission_{uuid4()}"
        payload = self.build_payload(action)

        self.pending_actions[request_id] = action

        if self.publish_request is not None:
            self.publish_request(request_id, json.dumps(payload))
        
        return request_id

    # ==================== INBOUND FLOW ====================
    def _task_id_from_response(self, response: dict[str, Any]) -> str | None:
        
        state = response.get("state")
        if not isinstance(state, dict):
            return None
        
        booking = state.get("booking")
        if not isinstance(booking, dict):
            return None
        
        task_id = booking.get("id")

        return task_id if isinstance(task_id, str) else None
    

    def handle_api_response(self, msg) -> str | None:
        # Handle incoming response messages from RMF

        responding_type = getattr(msg, "TYPE_RESPONDING", 2)
        if hasattr(msg, "type") and msg.type != responding_type:
            return None
        
        request_id = msg.request_id
        response_json = msg.json_msg
        
        # Pop the latest pending action
        action = self.pending_actions.pop(request_id, None)
        if action is None:
            return None

        response = json.loads(response_json)
        if not response.get("success"):
            self._log_warning(f"RMF rejected mission task: {response}")
            return None

        # Extract state.booking.id (task id)
        task_id = self._task_id_from_response(response)
        if task_id is None:
            self._log_warning(f"RMF task response has no task ID: {response}")
            return None

        # Record the accepted task with the misison manager
        if isinstance(action, DispatchTask):
            self.mission_manager.record_dispatch(action, task_id)
            context = TaskContext(
                mission_id=self.mission_manager.state.mission_id,
                robot_id=action.robot_id,
                package_id=action.package_id,
                segment=action.segment,
            )
        elif isinstance(action, PositionRobot):
            self.mission_manager.record_position_dispatch(action, task_id)
            context = TaskContext(
                mission_id=self.mission_manager.state.mission_id,
                robot_id=action.robot_id,
                package_id=None,
                segment=action.segment,
            )
        else:
            # Otherwise only create a task context with the home segment
            context = TaskContext(
                mission_id=self.mission_manager.state.mission_id,
                robot_id=action.robot_id,
                package_id=None,
                segment=TaskSegment.HOME,
            )

        self.task_context_by_id[task_id] = context # Store task context in task_context_by id
        # Once an RMF task is completed, THis context is used to emit correct mission event.

        return task_id

    def event_from_completed_task(self, task_id: str):
        # translates RMF task completion into mission events:
        if task_id in self.completed_task_ids:
            return None

        context = self.task_context_by_id.get(task_id)
        
        if context is None:
            return None

        self.completed_task_ids.add(task_id)

        if context.segment == TaskSegment.SOURCE_TO_STAGING:
            return RobotArrivedAtStaging(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment == TaskSegment.SOURCE_TO_TRANSFER:
            return UpstreamLegCompleted(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment == TaskSegment.STAGING_TO_TRANSFER:
            if context.robot_id == self.config.downstream_robot:
                return DownstreamPickupCompleted(
                    context.mission_id,
                    context.robot_id,
                    context.package_id,
                    task_id,
                )
            return UpstreamLegCompleted(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment == TaskSegment.HOME_TO_TRANSFER:
            return DownstreamPickupCompleted(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment == TaskSegment.DESTINATION_TO_TRANSFER:
            return DownstreamPickupCompleted(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment in (
            TaskSegment.HOME_TO_STAGING,
            TaskSegment.DESTINATION_TO_STAGING,
        ):
            return DownstreamRobotArrivedAtStaging(
                context.mission_id,
                context.robot_id,
                task_id,
            )
        if context.segment == TaskSegment.TRANSFER_TO_DESTINATION:
            return DownstreamLegCompleted(
                context.mission_id,
                context.robot_id,
                context.package_id,
                task_id,
            )
        if context.segment == TaskSegment.HOME:
            return RobotBecameIdle(context.mission_id, context.robot_id)
        return None

    def handle_task_state_update(self, task_state):
        if task_state.state != task_state.STATE_COMPLETED:
            return []
        
        event = self.event_from_completed_task(task_state.task_id)
        if event is None:
            return []
        return self.mission_manager.handle_event(event)


    def handle_tasks_msg(self, msg):
        actions = []
        for task_state in msg.tasks:
            actions.extend(self.handle_task_state_update(task_state))
        return actions

    def _log_warning(self, message: str) -> None:
        if self.logger is not None:
            self.logger.warning(message)
