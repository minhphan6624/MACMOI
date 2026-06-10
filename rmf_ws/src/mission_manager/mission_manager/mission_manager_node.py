import json

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rmf_fleet_msgs.msg import FleetState
from rmf_task_msgs.msg import ApiRequest, ApiResponse, TaskSummary
from std_msgs.msg import String

from .execution import ExecutionCommand, ExecutionCommandType
from .mission_definition import (
    DOWNSTREAM_ROBOT,
    FLEET_NAME,
    UPSTREAM_ROBOT,
)
from .mission_serializer import action_to_dict, event_to_dict, serialize_runtime_mission_state
from .mission_manager import MissionManager
from .rmf_execution_adapter import RmfExecutionAdapter, RmfExecutionAdapterConfig


class MissionManagerNode(Node):
    def __init__(self):
        super().__init__("mission_manager")

        self.declare_parameter("mission_id", "m1")
        self.declare_parameter("total_packages", 1)
        self.declare_parameter("auto_start", False)
        self.declare_parameter("task_summaries_topic", "task_summaries")
        self.declare_parameter("fleet_states_topic", "fleet_states")
        self.declare_parameter("mission_state_topic", "mission_state")
        self.declare_parameter("mission_commands_topic", "mission_commands")

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
            self.mission_manager.execution.mark_running(command_id)
            self.get_logger().info(f"Mission command accepted: {command_id}")
        self._publish_mission_state()

    def _handle_task_summaries(self, msg) -> None:
        commands = []
        task_states = getattr(msg, "tasks", [msg])
        for task_state in task_states:
            if task_state.state != task_state.STATE_COMPLETED:
                continue
            command_id = self.rmf_adapter.command_from_completed_task(task_state.task_id)
            if command_id is None:
                continue
            self._record_event(
                {
                    "type": "ExecutionCommandCompleted",
                    "command_id": command_id,
                    "rmf_task_id": task_state.task_id,
                }
            )
            commands.extend(self.mission_manager.complete_command(command_id))
        self._dispatch_commands(commands)

    def _handle_fleet_state(self, msg: FleetState) -> None:
        if msg.name != FLEET_NAME:
            return

        commands = []
        fleet_robots = {robot.name: robot for robot in msg.robots}
        for rmf_task_id, command_id in list(
            self.rmf_adapter.command_context_by_rmf_task_id.items()
        ):
            command = self.mission_manager.execution.commands.get(command_id)
            if command is None:
                continue

            fleet_robot = fleet_robots.get(command.robot_id)
            if fleet_robot is None or fleet_robot.task_id == rmf_task_id:
                continue

            mode = fleet_robot.mode
            if mode.mode == mode.MODE_MOVING:
                continue

            completed_command_id = self.rmf_adapter.command_from_completed_task(rmf_task_id)
            if completed_command_id is None:
                continue
            self._record_event(
                {
                    "type": "ExecutionCommandCompleted",
                    "command_id": completed_command_id,
                    "rmf_task_id": rmf_task_id,
                    "source": "fleet_state",
                }
            )
            commands.extend(self.mission_manager.complete_command(completed_command_id))

        self._dispatch_commands(commands)

    def _handle_mission_command(self, msg: String) -> None:
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

    def _dispatch_commands(self, commands: list[ExecutionCommand]) -> None:
        for command in commands:
            self._record_action(command)
            if command.command_type == ExecutionCommandType.MOVE_ROBOT:
                self.rmf_adapter.submit_command(command, self.mission_manager.runtime.world)
                self.mission_manager.execution.mark_submitted(command.command_id)
            elif command.command_type == ExecutionCommandType.HANDLE_ITEM:
                self._start_handling_timer(command)
            else:
                self.get_logger().warning(f"Unsupported execution command: {command}")
        self._publish_mission_state()

    def _start_handling_timer(self, command: ExecutionCommand) -> None:
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
        self.mission_manager.execution.mark_running(command.command_id)

        def on_timer():
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
            self._dispatch_commands(self.mission_manager.complete_command(command.command_id))

        timer_ref["timer"] = self.create_timer(seconds, on_timer)
        self.handling_timers.append(timer_ref["timer"])

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
