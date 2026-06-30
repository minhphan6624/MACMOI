import json
import math
from uuid import uuid4

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary
from std_msgs.msg import String

from .execution import ExecutionCommand, ExecutionCommandType
from .mission_definition import (
    DOWNSTREAM_ROBOT,
    UPSTREAM_ROBOT,
)
from .mission_serializer import (
    action_to_dict,
    serialize_mission_debug_state,
    serialize_mission_event,
    serialize_mission_state,
)
from .mission_events import (
    ExecutionCommandCancelled,
    ExecutionCommandCancelRequested,
    ExecutionCommandCompleted,
    ExecutionCommandFailed,
    ExecutionCommandRetry,
    MissionStartRequested,
    OperatorAbortRequested,
    OperatorPauseRequested,
    OperatorRobotPauseRequested,
    OperatorRobotResumeRequested,
    OperatorResumeRequested,
    RmfTaskSummaryCompleted,
)
from .mission_manager import MissionManager
from .rmf_adapter import RmfAdapter

class MissionManagerNode(Node):
    """ROS node that connects mission logic to RMF, Free Fleet, and topics."""

    def __init__(self):
        """Initialize ROS I/O, mission runtime, RMF adapter, and debug state."""

        super().__init__("mission_manager")

        self.declare_parameter("mission_id", "new-mission")
        self.declare_parameter("total_packages", 1)
        self.declare_parameter("auto_start", False)

        mission_id = self.get_parameter("mission_id").value
        total_packages = self.get_parameter("total_packages").value

        self.mission_manager = MissionManager.create_default(
            mission_id,
            total_packages,
            upstream_robot=UPSTREAM_ROBOT,
            downstream_robot=DOWNSTREAM_ROBOT,
        )

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        events_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.api_request_pub = self.create_publisher(ApiRequest, "task_api_requests", qos)

        # ---- Subscribers -----
        self.create_subscription(ApiResponse, "task_api_responses", self._handle_api_response, qos)
        self.create_subscription(TaskSummary, "task_summaries", self._handle_task_summaries, 10)
        self.create_subscription(String, "mission_commands", self._handle_operator_command, 10)
        self.create_subscription(String, "mission_execution_results", self._handle_execution_result, 10)

        # ----- Publishers -----

        self.mission_state_pub = self.create_publisher(String, "mission_state", qos)
        self.mission_debug_state_pub = self.create_publisher(String, "mission_debug_state", qos)
        self.mission_events_pub = self.create_publisher(String, "mission_events", events_qos)
        self.execution_command_pub = self.create_publisher(String, "mission_execution_commands", 10)

        self.rmf_adapter = RmfAdapter(
            mission_id=mission_id,
            publish_request=self._publish_api_request,
            logger=self.get_logger(),
        )

        self.recent_events = []
        self.recent_actions = []
        self.pending_speed_scale_requests = {}
        self.last_event = None
        self.last_action = None

        if self.get_parameter("auto_start").value:
            event = MissionStartRequested(source="auto_start")
            self._record_event(event)
            self._dispatch_commands(self.mission_manager.handle_event(event))
        else:
            self._publish_mission_state()

    # RMF API handlers
    def _publish_api_request(self, request_id: str, payload: str) -> None:
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = payload
        self.api_request_pub.publish(msg)
        self.get_logger().info(f"Published RMF task request {request_id}")

    def _handle_api_response(self, msg: ApiResponse) -> None:
        command_id = self.rmf_adapter.handle_api_response(msg)
        if command_id is not None:
            command = self.mission_manager.execution_manager.commands.get(command_id)
            if (
                command is not None
                and not command.is_terminal
            ):
                self.mission_manager.execution_manager.mark_running(command_id)
                self.get_logger().info(f"Execution command accepted: {command_id}")
        self._publish_mission_state()

    def _handle_task_summaries(self, msg) -> None:
        """Record RMF task completion."""

        task_states = getattr(msg, "tasks", [msg])
        for task_state in task_states:
            if task_state.state != task_state.STATE_COMPLETED:
                continue
            command_id = self.rmf_adapter.command_from_completed_task(task_state.task_id)
            if command_id is None:
                continue
            self._record_event(
                RmfTaskSummaryCompleted(command_id, task_state.task_id)
            )
        self._publish_mission_state()

    def _process_execution_event(self, event) -> list[ExecutionCommand]:
        """Record an execution event and let mission logic update state."""

        self._record_event(event)
        if isinstance(event, ExecutionCommandCompleted):
            self.get_logger().info(
                f"Execution command completed from {event.source}: "
                f"{event.command_id}"
            )
        return self.mission_manager.handle_event(event)

    def _handle_operator_command(self, msg: String) -> None:
        """Handle operator commands from the mission command topic."""

        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid operator command JSON: {msg.data}")
            return

        if command.get("mission_id") != self.mission_manager.runtime.mission_id:
            return

        if command.get("command") == "set_speed_scale":
            self._handle_speed_scale_command(command)
            return

        event = self._operator_event(
            command.get("command"),
            command.get("robot_id"),
        )
        if event is not None:
            self._record_event(event)
            if isinstance(event, OperatorRobotResumeRequested):
                self._publish_robot_control_command(event.robot_id, "resume_robot")
            self._dispatch_commands(self.mission_manager.handle_event(event))
            if isinstance(event, (OperatorPauseRequested, OperatorAbortRequested)):
                self._request_active_move_cancellations(
                    "operator_pause"
                    if isinstance(event, OperatorPauseRequested)
                    else "operator_abort"
                )
            elif isinstance(event, OperatorRobotPauseRequested):
                self._publish_robot_control_command(event.robot_id, "pause_robot")
                self._request_active_move_cancellations(
                    "operator_robot_pause",
                    event.robot_id,
                )
            return

        self.get_logger().warning(f"Unsupported operator command: {command}")

    def _handle_speed_scale_command(self, command: dict) -> None:
        robot_id = command.get("robot_id")
        scale = command.get("scale")
        if robot_id not in self.mission_manager.runtime.world.robots:
            self.get_logger().warning(f"Invalid speed scale robot_id: {robot_id}")
            return
        if (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or not 0.3 <= scale <= 1.0
        ):
            self.get_logger().warning(f"Invalid speed scale: {scale}")
            return

        scale = float(scale)
        request_id = str(uuid4())
        robot = self.mission_manager.runtime.world.robots[robot_id]
        robot.requested_speed_scale = scale
        self.pending_speed_scale_requests[request_id] = (robot_id, scale)
        self._publish_json(
            self.execution_command_pub,
            {
                "mission_id": self.mission_manager.runtime.mission_id,
                "command_type": "set_speed_scale",
                "control_request_id": request_id,
                "robot_id": robot_id,
                "scale": scale,
            },
        )
        self._publish_mission_state()

    def _operator_event(self, command: str | None, robot_id=None):
        if command == "start":
            return MissionStartRequested(source="operator")
        if command == "pause":
            return OperatorPauseRequested(source="operator")
        if command == "resume":
            return OperatorResumeRequested(source="operator")
        if command == "abort":
            return OperatorAbortRequested(source="operator")
        if (
            command in ("pause_robot", "resume_robot")
            and isinstance(robot_id, str)
            and robot_id in self.mission_manager.runtime.world.robots
        ):
            if command == "pause_robot":
                return OperatorRobotPauseRequested(robot_id, source="operator")
            return OperatorRobotResumeRequested(robot_id, source="operator")
        return None

    def _handle_execution_result(self, msg: String) -> None:
        """Handle direct execution results from the Free Fleet/Nav2 side channel."""

        try:
            result = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid execution result JSON: {msg.data}")
            return

        if result.get("mission_id") != self.mission_manager.runtime.mission_id:
            return

        if result.get("command_type") == "set_speed_scale":
            self._handle_speed_scale_result(result)
            return

        command_id = result.get("command_id")
        if not isinstance(command_id, str):
            self.get_logger().warning(f"Execution result missing command_id: {result}")
            return

        command = self.mission_manager.execution_manager.commands.get(command_id)
        if command is None or command.is_terminal:
            return

        status = result.get("status")
        source = result.get("source", "execution_result")
        if status == "SUCCEEDED":

            if command.command_type == ExecutionCommandType.MOVE_ROBOT:
                failure = self._move_completion_failure(command, result)
                if failure is not None:
                    error, details = failure
                    commands = self._process_execution_event(
                        ExecutionCommandFailed(command_id, error, source, details)
                    )
                    self._dispatch_after_execution_failure(
                        command_id,
                        error,
                        commands,
                    )
                    return

            commands = self._process_execution_event(
                ExecutionCommandCompleted(command_id, source, result.get("rmf_task_id"))
            )
            self._dispatch_commands(commands)
            return

        if status == "CANCELLED":
            reason = (
                result.get("cancel_reason")
                or result.get("error")
                or "CANCELLED"
            )
            commands = self._process_execution_event(
                ExecutionCommandCancelled(command_id, reason, source, self._execution_failure_details(command, result))
            )
            self._dispatch_commands(commands)
            return

        if status == "FAILED":
            error = result.get("error") or status
            commands = self._process_execution_event(
                ExecutionCommandFailed(command_id, error, source, self._execution_failure_details(command, result))
            )
            self._dispatch_after_execution_failure(command_id, error, commands)

    def _handle_speed_scale_result(self, result: dict) -> None:
        request_id = result.get("control_request_id")
        pending = self.pending_speed_scale_requests.pop(request_id, None)
        if pending is None:
            return

        robot_id, scale = pending
        if result.get("status") == "SUCCEEDED":
            self.mission_manager.runtime.world.robots[robot_id].speed_scale = scale
            self.get_logger().info(
                f"Confirmed speed scale {scale} for robot {robot_id}"
            )
        else:
            self.get_logger().warning(
                f"Failed to set speed scale for {robot_id}: "
                f"{result.get('error', 'unknown error')}"
            )
        self._publish_mission_state()

    def _request_active_move_cancellations(
        self,
        reason: str,
        robot_id: str | None = None,
    ) -> None:
        for command in self._active_execution_commands():
            if command.command_type != ExecutionCommandType.MOVE_ROBOT:
                continue
            if robot_id is not None and command.robot_id != robot_id:
                continue
            self._record_event(
                ExecutionCommandCancelRequested(
                    command.command_id,
                    reason,
                    "mission_manager_node",
                    {
                        "robot_id": command.robot_id,
                        "target": command.target,
                    },
                )
            )
            self._publish_execution_cancel_request(command, reason)
        self._publish_mission_state()

    def _active_execution_commands(self) -> list[ExecutionCommand]:
        return [
            command
            for command in self.mission_manager.execution_manager.commands.values()
            if not command.is_terminal
        ]

    def _dispatch_after_execution_failure(
        self,
        failed_command_id: str,
        reason: str,
        commands: list[ExecutionCommand],
    ) -> None:
        if commands:
            self._record_event(
                ExecutionCommandRetry(
                    failed_command_id,
                    [command.command_id for command in commands],
                    reason,
                )
            )
        self._dispatch_commands(commands)

    def _move_completion_failure(
        self,
        command: ExecutionCommand,
        result: dict,
    ) -> tuple[str, dict] | None:
        """Return failure details if a reported move success should be rejected."""

        source = result.get("source", "execution_result")
        details = self._execution_failure_details(command, result)

        if source not in ("nav2_result", "nav2_already_near_target"):
            self.get_logger().warning(
                f"Rejected move completion for {command.command_id}: "
                "unsupported_move_result_source"
            )
            return "unsupported_move_result_source", details

        if result.get("arrival_verified") is not True:
            self.get_logger().warning(
                f"Rejected move completion for {command.command_id}: "
                "arrival_not_verified"
            )
            return "arrival_not_verified", details

        return None

    def _execution_failure_details(
        self,
        command: ExecutionCommand,
        result: dict,
    ) -> dict:
        details = {
            "robot_id": command.robot_id,
            "target": command.target,
        }
        for key in (
            "status",
            "rmf_task_id",
            "distance_to_target",
            "arrival_tolerance_m",
            "arrival_verified",
        ):
            if key in result:
                details[key] = result.get(key)
        return details

    def _dispatch_commands(self, commands: list[ExecutionCommand]) -> None:
        """Send emitted execution commands to RMF or local handling simulation."""

        for command in commands:
            self._record_action(command)

            if command.command_type == ExecutionCommandType.MOVE_ROBOT:
                self._publish_execution_command(command)
                self.rmf_adapter.submit_command(command)
                self.mission_manager.execution_manager.mark_submitted(command.command_id)

            elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
                self._publish_execution_command(command)
                self.mission_manager.execution_manager.mark_submitted(command.command_id)
                self.mission_manager.execution_manager.mark_running(command.command_id)

            else:
                self.get_logger().warning(f"Unsupported execution command: {command}")

        self._publish_mission_state()

    # ----- Topic publishing helpers -----

    def _record_event(self, event) -> None:
        event_dict = serialize_mission_event(
            event,
            self.mission_manager.runtime.mission_id,
        )
        if event_dict is None:
            return
        self.last_event = event_dict
        self.recent_events.append(event_dict)
        self.recent_events = self.recent_events[-20:]

        self._publish_json(self.mission_events_pub, event_dict)

    def _record_action(self, action) -> None:
        action_dict = action_to_dict(action)
        self.last_action = action_dict
        self.recent_actions.append(action_dict)
        self.recent_actions = self.recent_actions[-20:]

    def _publish_mission_state(self) -> None:
        """Publish the current serialized mission state."""

        self._publish_json(
            self.mission_state_pub,
            serialize_mission_state(
                self.mission_manager,
                self.rmf_adapter,
                self.last_event,
            ),
        )

        self._publish_json(
            self.mission_debug_state_pub,
            serialize_mission_debug_state(
                self.mission_manager,
                self.rmf_adapter,
                {
                    "last_event": self.last_event,
                    "last_action": self.last_action,
                    "recent_events": self.recent_events,
                    "recent_actions": self.recent_actions,
                },
            )
        )

    def _publish_execution_command(self, command: ExecutionCommand) -> None:
        """Publish command context for external execution result producers."""

        payload = self._execution_command_payload(command, command.command_type.value)

        if command.target is not None:
            payload["target"] = command.target
        if command.item_id is not None:
            payload["item_id"] = command.item_id
        if command.handling_type is not None:
            payload["handling_type"] = command.handling_type

        self._publish_json(self.execution_command_pub, payload)

    def _publish_execution_cancel_request(
        self,
        command: ExecutionCommand,
        reason: str,
    ) -> None:
        self._publish_json(
            self.execution_command_pub,
            {
                **self._execution_command_payload(command, "cancel_move"),
                "cancel_reason": reason,
            },
        )

    def _publish_robot_control_command(
        self,
        robot_id: str,
        command_type: str,
    ) -> None:
        self._publish_json(
            self.execution_command_pub,
            {
                "mission_id": self.mission_manager.runtime.mission_id,
                "robot_id": robot_id,
                "command_type": command_type,
            },
        )

    def _execution_command_payload(
        self,
        command: ExecutionCommand,
        command_type: str,
    ) -> dict:
        return {
            "mission_id": self.mission_manager.runtime.mission_id,
            "command_id": command.command_id,
            "task_id": command.task_id,
            "robot_id": command.robot_id,
            "command_type": command_type,
        }

    def _publish_json(self, publisher, payload: dict) -> None:
        msg = String()
        msg.data = json.dumps(payload)
        publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = MissionManagerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
