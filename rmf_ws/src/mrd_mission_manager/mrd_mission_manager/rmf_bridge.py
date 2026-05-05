import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .actions import DispatchTask, SendRobotHome
from .events import (
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
        self.publish_request = publish_request
        self.logger = logger
        self.pending_actions: dict[str, DispatchTask | SendRobotHome] = {}
        self.task_context_by_id: dict[str, TaskContext] = {}
        self.completed_task_ids: set[str] = set()

    def submit_action(self, action: DispatchTask | SendRobotHome) -> str | None:
        if not isinstance(action, (DispatchTask, SendRobotHome)):
            return None

        request_id = f"mission_{uuid4()}"
        payload = self.build_payload(action)
        self.pending_actions[request_id] = action
        if self.publish_request is not None:
            self.publish_request(request_id, json.dumps(payload))
        return request_id

    def build_payload(self, action: DispatchTask | SendRobotHome) -> dict[str, Any]:
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
                    "places": self.places_for(robot_id, segment),
                    "rounds": 1,
                },
                "labels": labels,
                "requester": self.config.requester,
            },
        }

    def places_for(self, robot_id: str, segment: TaskSegment) -> list[str]:
        if segment == TaskSegment.SOURCE_TO_STAGING:
            return [self.config.source_waypoint, self.config.staging_waypoint]
        if segment == TaskSegment.STAGING_TO_TRANSFER:
            return [self.config.staging_waypoint, self.config.transfer_waypoint]
        if segment == TaskSegment.HOME_TO_TRANSFER:
            return [self.home_waypoint(robot_id), self.config.transfer_waypoint]
        if segment == TaskSegment.TRANSFER_TO_DESTINATION:
            return [self.config.transfer_waypoint, self.config.destination_waypoint]
        if segment == TaskSegment.HOME:
            return [self.home_waypoint(robot_id)]
        raise ValueError(f"Unsupported task segment: {segment}")

    def home_waypoint(self, robot_id: str) -> str:
        if robot_id == self.config.upstream_robot:
            return self.config.upstream_home_waypoint
        if robot_id == self.config.downstream_robot:
            return self.config.downstream_home_waypoint
        return self.config.upstream_home_waypoint

    def handle_api_response_msg(self, msg) -> str | None:
        responding_type = getattr(msg, "TYPE_RESPONDING", 2)
        if hasattr(msg, "type") and msg.type != responding_type:
            return None
        return self.handle_api_response(msg.request_id, msg.json_msg)

    def handle_api_response(self, request_id: str, response_json: str) -> str | None:
        action = self.pending_actions.pop(request_id, None)
        if action is None:
            return None

        response = json.loads(response_json)
        if not response.get("success"):
            self._log_warning(f"RMF rejected mission task: {response}")
            return None

        task_id = self._task_id_from_response(response)
        if task_id is None:
            self._log_warning(f"RMF task response has no task ID: {response}")
            return None

        if isinstance(action, DispatchTask):
            self.mission_manager.record_dispatch(action, task_id)
            context = TaskContext(
                mission_id=self.mission_manager.state.mission_id,
                robot_id=action.robot_id,
                package_id=action.package_id,
                segment=action.segment,
            )
        else:
            context = TaskContext(
                mission_id=self.mission_manager.state.mission_id,
                robot_id=action.robot_id,
                package_id=None,
                segment=TaskSegment.HOME,
            )

        self.task_context_by_id[task_id] = context
        return task_id

    def handle_completed_task(self, task_id: str):
        event = self.event_from_completed_task(task_id)
        if event is None:
            return []
        return self.mission_manager.handle_event(event)

    def event_from_completed_task(self, task_id: str):
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
        if context.segment == TaskSegment.STAGING_TO_TRANSFER:
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
        task_id = self._task_id_from_task_state(task_state)
        if task_id is None or not self._task_is_completed(task_state):
            return []
        return self.handle_completed_task(task_id)

    def handle_tasks_msg(self, msg):
        actions = []
        for task_state in getattr(msg, "tasks", []):
            actions.extend(self.handle_task_state_update(task_state))
        return actions

    def _task_id_from_response(self, response: dict[str, Any]) -> str | None:
        state = response.get("state")
        if not isinstance(state, dict):
            return None
        booking = state.get("booking")
        if not isinstance(booking, dict):
            return None
        task_id = booking.get("id")
        return task_id if isinstance(task_id, str) else None

    def _task_id_from_task_state(self, task_state) -> str | None:
        if isinstance(task_state, dict):
            booking = task_state.get("booking")
            if isinstance(booking, dict):
                task_id = booking.get("id")
                return task_id if isinstance(task_id, str) else None
            task_id = task_state.get("task_id")
            return task_id if isinstance(task_id, str) else None

        if hasattr(task_state, "booking") and hasattr(task_state.booking, "id"):
            return task_state.booking.id
        if hasattr(task_state, "task_id"):
            return task_state.task_id
        return None

    def _task_is_completed(self, task_state) -> bool:
        if isinstance(task_state, dict):
            return task_state.get("status") == "completed" or task_state.get("state") == 2

        status = getattr(task_state, "status", None)
        if status == "completed":
            return True

        state = getattr(task_state, "state", None)
        completed_value = getattr(task_state, "STATE_COMPLETED", 2)
        return state == completed_value

    def _log_warning(self, message: str) -> None:
        if self.logger is not None:
            self.logger.warning(message)
