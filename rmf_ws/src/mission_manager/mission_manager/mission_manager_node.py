import json

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary
from std_msgs.msg import String

from .execution import ExecutionCommand, ExecutionCommandStatus, ExecutionCommandType
from .mission_definition import (
    DOWNSTREAM_ROBOT,
    UPSTREAM_ROBOT,
)
from .mission_serializer import action_to_dict, event_to_dict, serialize_runtime_mission_state
from .mission_manager import MissionManager
from .rmf_adapter import RmfAdapter


TASK_API_REQUESTS_TOPIC = "task_api_requests"
TASK_API_RESPONSES_TOPIC = "task_api_responses"
TASK_SUMMARIES_TOPIC = "task_summaries"
MISSION_STATE_TOPIC = "mission_state"
MISSION_COMMANDS_TOPIC = "mission_commands"
MISSION_EXECUTION_COMMANDS_TOPIC = "mission_execution_commands"
MISSION_EXECUTION_RESULTS_TOPIC = "mission_execution_results"


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
        self.api_request_pub = self.create_publisher(
            ApiRequest,
            TASK_API_REQUESTS_TOPIC,
            qos,
        )
        self.create_subscription(
            ApiResponse,
            TASK_API_RESPONSES_TOPIC,
            self._handle_api_response,
            qos,
        )
        self.create_subscription(
            TaskSummary,
            TASK_SUMMARIES_TOPIC,
            self._handle_task_summaries,
            10,
        )
        self.mission_state_pub = self.create_publisher(
            String,
            MISSION_STATE_TOPIC,
            qos,
        )
        self.create_subscription(
            String,
            MISSION_COMMANDS_TOPIC,
            self._handle_mission_command,
            10,
        )
        self.execution_command_pub = self.create_publisher(
            String,
            MISSION_EXECUTION_COMMANDS_TOPIC,
            10,
        )
        self.create_subscription(
            String,
            MISSION_EXECUTION_RESULTS_TOPIC,
            self._handle_execution_result,
            10,
        )

        self.rmf_adapter = RmfAdapter(
            mission_id=mission_id,
            publish_request=self._publish_api_request,
            logger=self.get_logger(),
        )

        self.recent_events = []
        self.recent_actions = []
        self.active_handling_commands = []
        self.last_event = None
        self.last_action = None

        if self.get_parameter("auto_start").value:
            self._record_event({"command": "auto_start", "mission_id": mission_id})
            self._dispatch_commands(self.mission_manager.start())
        else:
            self._publish_mission_state()

    def _publish_api_request(self, request_id: str, payload: str) -> None:
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = payload
        self.api_request_pub.publish(msg)
        self.get_logger().info(f"Published mission command request {request_id}")

    def _handle_api_response(self, msg: ApiResponse) -> None:
        command_id = self.rmf_adapter.handle_api_response(msg)
        if command_id is not None:
            self.mission_manager.execution_manager.mark_running(command_id)
            self.get_logger().info(f"Mission command accepted: {command_id}")
        self._publish_mission_state()

    def _handle_task_summaries(self, msg) -> None:
        """Complete mission commands from RMF task summary completion events."""

        commands = []
        task_states = getattr(msg, "tasks", [msg])
        for task_state in task_states:
            if task_state.state != task_state.STATE_COMPLETED:
                continue
            command_id = self.rmf_adapter.command_from_completed_task(task_state.task_id)
            if command_id is None:
                continue
            commands.extend(
                self._complete_execution_command(
                    command_id,
                    "task_summary",
                    task_state.task_id,
                )
            )
        self._dispatch_commands(commands)

    def _is_terminal_command(self, command: ExecutionCommand) -> bool:
        return command.status in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        )

    def _complete_execution_command(
        self,
        command_id: str,
        source: str,
        rmf_task_id: str | None = None,
    ) -> list[ExecutionCommand]:
        """Record command completion and let mission logic advance."""

        self._record_event(
            {
                "type": "ExecutionCommandCompleted",
                "command_id": command_id,
                "rmf_task_id": rmf_task_id,
                "source": source,
            }
        )
        self.get_logger().info(
            f"Mission command completed from {source}: {command_id}"
        )
        return self.mission_manager.complete_command(command_id)

    def _handle_mission_command(self, msg: String) -> None:
        """Handle operator mission commands from the mission command topic."""

        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid mission command JSON: {msg.data}")
            return

        if command.get("mission_id") != self.mission_manager.runtime.mission_id:
            return

        if command.get("command") == "start":
            self._record_event(command)
            self._dispatch_commands(self.mission_manager.start())
            return

        self.get_logger().warning(f"Unsupported mission command: {command}")

    def _handle_execution_result(self, msg: String) -> None:
        """Handle direct execution results from the Free Fleet/Nav2 side channel."""

        try:
            result = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid execution result JSON: {msg.data}")
            return

        if result.get("mission_id") != self.mission_manager.runtime.mission_id:
            return

        command_id = result.get("command_id")
        if not isinstance(command_id, str):
            self.get_logger().warning(f"Execution result missing command_id: {result}")
            return

        command = self.mission_manager.execution_manager.commands.get(command_id)
        if command is None or self._is_terminal_command(command):
            return

        status = result.get("status")
        if status == "SUCCEEDED":
            # Remove completed robot-side handling command from mission_state debug data.
            self.active_handling_commands = [
                command
                for command in self.active_handling_commands
                if command.get("command_id") != command_id
            ]
            commands = self._complete_execution_command(
                command_id,
                result.get("source", "execution_result"),
                result.get("rmf_task_id"),
            )
            self._dispatch_commands(commands)
            return

        if status in ("FAILED", "CANCELLED"):
            error = result.get("error") or status
            self.mission_manager.execution_manager.mark_failed(command_id, error)
            # Remove failed/cancelled robot-side handling command from mission_state debug data.
            self.active_handling_commands = [
                command
                for command in self.active_handling_commands
                if command.get("command_id") != command_id
            ]
            self._record_event(result)
            self._publish_mission_state()

    def _dispatch_commands(self, commands: list[ExecutionCommand]) -> None:
        """Send emitted mission commands to RMF or local handling simulation."""

        for command in commands:
            self._record_action(command)
            if command.command_type == ExecutionCommandType.MOVE_ROBOT:
                self._publish_execution_command(command)
                self.rmf_adapter.submit_command(command)
                self.mission_manager.execution_manager.mark_submitted(command.command_id)
            elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
                self._publish_execution_command(command)
                # Expose the outstanding robot-side handling command in mission_state debug data.
                self.active_handling_commands.append(
                    {
                        "command_id": command.command_id,
                        "robot_id": command.robot_id,
                        "item_id": command.item_id,
                        "handling_type": command.handling_type,
                    }
                )
                self.mission_manager.execution_manager.mark_submitted(command.command_id)
                self.mission_manager.execution_manager.mark_running(command.command_id)
            else:
                self.get_logger().warning(f"Unsupported execution command: {command}")
        self._publish_mission_state()

    def _publish_execution_command(self, command: ExecutionCommand) -> None:
        """Publish command context for external execution result producers."""

        msg = String()

        payload = {
            "mission_id": self.mission_manager.runtime.mission_id,
            "command_id": command.command_id,
            "task_id": command.task_id,
            "robot_id": command.robot_id,
            "command_type": command.command_type.value,
        }

        if command.target is not None:
            payload["target"] = command.target
        if command.item_id is not None:
            payload["item_id"] = command.item_id
        if command.handling_type is not None:
            payload["handling_type"] = command.handling_type

        msg.data = json.dumps(payload)
        self.execution_command_pub.publish(msg)

    # ----- Topic publishing helpers -----

    def _record_event(self, event) -> None:
        event_dict = event_to_dict(event)
        self.last_event = event_dict
        self.recent_events.append(event_dict)
        self.recent_events = self.recent_events[-20:]

    def _record_action(self, action) -> None:
        action_dict = action_to_dict(action)
        self.last_action = action_dict
        self.recent_actions.append(action_dict)
        self.recent_actions = self.recent_actions[-20:]

    def _publish_mission_state(self) -> None:
        """Publish the current serialized mission state."""

        msg = String()
        msg.data = json.dumps(
            serialize_runtime_mission_state(
                self.mission_manager,
                self.rmf_adapter,
                {
                    "last_event": self.last_event,
                    "last_action": self.last_action,
                    "recent_events": self.recent_events,
                    "recent_actions": self.recent_actions,
                    "active_handling_commands": self.active_handling_commands,
                },
            )
        )
        self.mission_state_pub.publish(msg)


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
