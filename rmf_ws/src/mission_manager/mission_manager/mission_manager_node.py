import json
import math

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary
from std_msgs.msg import String

from .execution import ExecutionCommand, ExecutionCommandStatus, ExecutionCommandType
from .mission_definition import (
    DESTINATION_WAYPOINT,
    DOWNSTREAM_ROBOT,
    DOWNSTREAM_HOME_WAYPOINT,
    FLEET_NAME,
    SOURCE_WAYPOINT,
    TRANSFER_DOWNSTREAM_EXIT_WAYPOINT,
    TRANSFER_UPSTREAM_EXIT_WAYPOINT,
    TRANSFER_WAYPOINT,
    UPSTREAM_ROBOT,
    UPSTREAM_HOME_WAYPOINT,
)
from .mission_serializer import action_to_dict, event_to_dict, serialize_runtime_mission_state
from .mission_manager import MissionManager
from .rmf_execution_adapter import RmfExecutionAdapter, RmfExecutionAdapterConfig


class MissionManagerNode(Node):
    """ROS node that connects mission logic to RMF, Free Fleet, and topics."""

    WAYPOINTS = {
        TRANSFER_WAYPOINT: {"index": 1, "position": (12.942662582931954, -5.815638350433473)},
        DESTINATION_WAYPOINT: {"index": 2, "position": (9.897501485095004, -5.772506176387456)},
        SOURCE_WAYPOINT: {"index": 3, "position": (15.633784531333973, -5.781093130945816)},
        DOWNSTREAM_HOME_WAYPOINT: {"index": 4, "position": (10.706303773928157, -3.710551375482774)},
        UPSTREAM_HOME_WAYPOINT: {"index": 5, "position": (15.554725329020794, -3.8208986765890605)},
        TRANSFER_DOWNSTREAM_EXIT_WAYPOINT: {"index": 6, "position": (11.683390631979744, -4.965924651664219)},
        TRANSFER_UPSTREAM_EXIT_WAYPOINT: {"index": 7, "position": (14.25340691092075, -5.024207371971251)},
    }

    def __init__(self):
        """Initialize ROS I/O, mission runtime, RMF adapter, and debug state."""

        super().__init__("mission_manager")

        self.declare_parameter("mission_id", "m1")
        self.declare_parameter("total_packages", 1)
        self.declare_parameter("auto_start", False)
        self.declare_parameter("task_summaries_topic", "task_summaries")
        self.declare_parameter("fleet_states_topic", "fleet_states")
        self.declare_parameter("mission_state_topic", "mission_state")
        self.declare_parameter("mission_commands_topic", "mission_commands")
        self.declare_parameter("mission_execution_commands_topic", "mission_execution_commands")
        self.declare_parameter("mission_execution_results_topic", "mission_execution_results")
        self.declare_parameter("enable_fleet_state_completion_fallback", True)
        self.declare_parameter("target_position_tolerance", 0.35)

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
            "task_api_requests",
            qos,
        )
        self.create_subscription(
            ApiResponse,
            "task_api_responses",
            self._handle_api_response,
            qos,
        )
        self.create_subscription(
            TaskSummary,
            self.get_parameter("task_summaries_topic").value,
            self._handle_task_summaries,
            10,
        )
        self.create_subscription(
            FleetState,
            self.get_parameter("fleet_states_topic").value,
            self._handle_fleet_state,
            10,
        )
        self.mission_state_pub = self.create_publisher(
            String,
            self.get_parameter("mission_state_topic").value,
            qos,
        )
        self.create_subscription(
            String,
            self.get_parameter("mission_commands_topic").value,
            self._handle_mission_command,
            10,
        )
        self.execution_command_pub = self.create_publisher(
            String,
            self.get_parameter("mission_execution_commands_topic").value,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter("mission_execution_results_topic").value,
            self._handle_execution_result,
            10,
        )

        self.rmf_adapter = RmfExecutionAdapter(
            RmfExecutionAdapterConfig(),
            publish_request=self._publish_api_request,
            logger=self.get_logger(),
        )
        self.handling_timers = []
        self.recent_events = []
        self.recent_actions = []
        self.active_handling_timers = []
        self.last_event = None
        self.last_action = None
        self.enable_fleet_state_completion_fallback = bool(
            self.get_parameter("enable_fleet_state_completion_fallback").value
        )
        self.target_position_tolerance = float(
            self.get_parameter("target_position_tolerance").value
        )

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

    def _handle_fleet_state(self, msg: FleetState) -> None:
        """Use fleet state as a fallback completion source for move commands."""

        if msg.name != FLEET_NAME:
            return
        if not self.enable_fleet_state_completion_fallback:
            self._publish_mission_state()
            return

        commands = []
        fleet_robots = {robot.name: robot for robot in msg.robots}
        for rmf_task_id, command_id in list(
            self.rmf_adapter.command_id_by_rmf_task_id.items()
        ):
            command = self.mission_manager.execution_manager.commands.get(command_id)
            if command is None or self._is_terminal_command(command):
                continue

            fleet_robot = fleet_robots.get(command.robot_id)
            if fleet_robot is None:
                continue

            mode = fleet_robot.mode
            if mode.mode == mode.MODE_MOVING:
                continue

            if not self._robot_reached_command_target(fleet_robot, command):
                continue

            completed_command_id = self.rmf_adapter.command_from_completed_task(
                rmf_task_id
            )
            if completed_command_id is None:
                continue
            commands.extend(
                self._complete_execution_command(
                    completed_command_id,
                    "fleet_state_target_pose",
                    rmf_task_id,
                )
            )

        self._dispatch_commands(commands)

    def _is_terminal_command(self, command: ExecutionCommand) -> bool:
        return command.status in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        )

    def _robot_reached_command_target(self, fleet_robot, command: ExecutionCommand) -> bool:
        """Return whether a fleet robot appears to have reached a command target."""

        if command.command_type != ExecutionCommandType.MOVE_ROBOT:
            return False
        if command.target is None:
            return False

        waypoint = self.WAYPOINTS.get(command.target)
        if waypoint is None:
            return False

        location = fleet_robot.location
        if int(location.index) == waypoint["index"]:
            return True

        target_x, target_y = waypoint["position"]
        distance = math.hypot(location.x - target_x, location.y - target_y)
        return distance <= self.target_position_tolerance

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
            self._record_event(result)
            self._publish_mission_state()

    def _dispatch_commands(self, commands: list[ExecutionCommand]) -> None:
        """Send emitted mission commands to RMF or local handling simulation."""

        for command in commands:
            self._record_action(command)
            if command.command_type == ExecutionCommandType.MOVE_ROBOT:
                self._publish_execution_command(command)
                self.rmf_adapter.submit_command(command, self.mission_manager.runtime.world)
                self.mission_manager.execution_manager.mark_submitted(command.command_id)
            elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
                self._start_handling_timer(command)
            else:
                self.get_logger().warning(f"Unsupported execution command: {command}")
        self._publish_mission_state()

    def _publish_execution_command(self, command: ExecutionCommand) -> None:
        """Publish command context for external execution result producers."""

        if command.target is None:
            return

        msg = String()
        msg.data = json.dumps(
            {
                "mission_id": self.mission_manager.runtime.mission_id,
                "command_id": command.command_id,
                "task_id": command.task_id,
                "robot_id": command.robot_id,
                "target": command.target,
                "command_type": command.command_type.value,
            }
        )
        self.execution_command_pub.publish(msg)

    def _start_handling_timer(self, command: ExecutionCommand) -> None:
        """Simulate package load/unload completion with a short ROS timer."""

        seconds = 5.0
        timer_ref = {}
        timer_info = {
            "command_id": command.command_id,
            "robot_id": command.robot_id,
            "item_id": command.item_id,
            "handling_type": command.handling_type,
            "seconds": seconds,
        }
        self.active_handling_timers.append(timer_info)
        self.mission_manager.execution_manager.mark_running(command.command_id)

        def on_timer():
            """Complete the simulated package handling command."""

            timer_ref["timer"].cancel()
            if timer_info in self.active_handling_timers:
                self.active_handling_timers.remove(timer_info)
            self._record_event(
                {
                    "type": "ExecutionCommandCompleted",
                    "command_id": command.command_id,
                    "source": "handling_timer",
                }
            )
            self.get_logger().info(
                f"Mission command completed from handling_timer: {command.command_id}"
            )
            self._dispatch_commands(self.mission_manager.complete_command(command.command_id))

        timer_ref["timer"] = self.create_timer(seconds, on_timer)
        self.handling_timers.append(timer_ref["timer"])

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
                    "active_handling_timers": self.active_handling_timers,
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
