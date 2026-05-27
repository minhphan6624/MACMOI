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

from .actions import DispatchTask, PositionRobot, SendRobotHome, StartHandlingTimer
from .events import HandlingTimerCompleted, MissionStarted
from .mission_manager import MissionManager
from .mission_serializer import action_to_dict, event_to_dict, serialize_mission_state
from .mission_state import RobotLocation
from .rmf_bridge import MissionBridgeConfig, RmfMissionBridge


class MissionManagerNode(Node):
    def __init__(self):
        super().__init__("mrd_mission_manager")

        self.declare_parameter("mission_id", "m1")
        self.declare_parameter("total_packages", 1)
        self.declare_parameter("auto_start", False)
        self.declare_parameter("fleet_name", "tb3_lab")
        self.declare_parameter("upstream_robot", "tb3_1")
        self.declare_parameter("downstream_robot", "tb3_2")
        self.declare_parameter("source_waypoint", "wp1")
        self.declare_parameter("staging_waypoint", "wp2")
        self.declare_parameter("transfer_waypoint", "wp3")
        self.declare_parameter("destination_waypoint", "wp4")
        self.declare_parameter("upstream_home_waypoint", "wp1")
        self.declare_parameter("downstream_home_waypoint", "wp2")
        self.declare_parameter("task_summaries_topic", "task_summaries")
        self.declare_parameter("fleet_states_topic", "fleet_states")
        self.declare_parameter("mission_state_topic", "mission_state")
        self.declare_parameter("mission_commands_topic", "mission_commands")

        mission_id = self.get_parameter("mission_id").value
        total_packages = self.get_parameter("total_packages").value
        upstream_robot = self.get_parameter("upstream_robot").value
        downstream_robot = self.get_parameter("downstream_robot").value
        staging_waypoint = self.get_parameter("staging_waypoint").value
        downstream_home_waypoint = self.get_parameter("downstream_home_waypoint").value
        self.manager = MissionManager.create(
            mission_id,
            total_packages,
            upstream_robot=upstream_robot,
            downstream_robot=downstream_robot,
        )
        if downstream_home_waypoint == staging_waypoint:
            self.manager.state.robots[downstream_robot].location = RobotLocation.STAGING

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

        self.bridge = RmfMissionBridge(
            self.manager,
            MissionBridgeConfig(
                fleet_name=self.get_parameter("fleet_name").value,
                upstream_robot=upstream_robot,
                downstream_robot=downstream_robot,
                source_waypoint=self.get_parameter("source_waypoint").value,
                staging_waypoint=staging_waypoint,
                transfer_waypoint=self.get_parameter("transfer_waypoint").value,
                destination_waypoint=self.get_parameter("destination_waypoint").value,
                upstream_home_waypoint=self.get_parameter("upstream_home_waypoint").value,
                downstream_home_waypoint=downstream_home_waypoint,
            ),
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
            self._handle_event(MissionStarted(mission_id))
        else:
            self._publish_mission_state()

    def _publish_api_request(self, request_id: str, payload: str) -> None:
        msg = ApiRequest()
        msg.request_id = request_id
        msg.json_msg = payload
        self.api_request_pub.publish(msg)
        self.get_logger().info(f"Published mission task request {request_id}")

    def _handle_api_response(self, msg: ApiResponse) -> None:
        task_id = self.bridge.handle_api_response(msg)
        if task_id is not None:
            self.get_logger().info(f"Mission task accepted: {task_id}")
        self._publish_mission_state()

    def _handle_task_summaries(self, msg) -> None:
        actions = []
        task_states = getattr(msg, "tasks", [msg])
        for task_state in task_states:
            if task_state.state != task_state.STATE_COMPLETED:
                continue
            event = self.bridge.event_from_completed_task(task_state.task_id)
            if event is None:
                continue
            self._record_event(event)
            actions.extend(self.manager.handle_event(event))
        self._dispatch_actions(actions)

    def _handle_fleet_state(self, msg: FleetState) -> None:
        if msg.name != self.get_parameter("fleet_name").value:
            return

        actions = []
        fleet_robots = {robot.name: robot for robot in msg.robots}
        for mission_robot in self.manager.state.robots.values():
            active_task_id = mission_robot.active_task_id
            if active_task_id is None:
                continue

            fleet_robot = fleet_robots.get(mission_robot.robot_id)
            if fleet_robot is None or fleet_robot.task_id == active_task_id:
                continue

            mode = fleet_robot.mode
            if mode.mode == mode.MODE_MOVING:
                continue

            event = self.bridge.event_from_completed_task(active_task_id)
            if event is None:
                continue
            self._record_event(event)
            actions.extend(self.manager.handle_event(event))

        self._dispatch_actions(actions)

    def _handle_mission_command(self, msg: String) -> None:
        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid mission command JSON: {msg.data}")
            return

        if command.get("mission_id") != self.manager.state.mission_id:
            return

        if command.get("command") == "start":
            self._handle_event(MissionStarted(self.manager.state.mission_id))
            return

        self.get_logger().warning(f"Unsupported mission command: {command}")

    def _dispatch_actions(self, actions) -> None:
        for action in actions:
            self._record_action(action)
            if isinstance(action, (DispatchTask, PositionRobot, SendRobotHome)):
                self.bridge.submit_action(action)
            elif isinstance(action, StartHandlingTimer):
                self._start_handling_timer(action)
            else:
                self.get_logger().info(f"Mission action: {action}")
        self._publish_mission_state()

    def _start_handling_timer(self, action: StartHandlingTimer) -> None:
        timer_ref = {}
        timer_info = {
            "robot_id": action.robot_id,
            "package_id": action.package_id,
            "handling_type": action.handling_type,
            "seconds": action.seconds,
        }
        self.active_handling_timers.append(timer_info)

        def on_timer():
            timer_ref["timer"].cancel()
            if timer_info in self.active_handling_timers:
                self.active_handling_timers.remove(timer_info)
            self._handle_event(
                HandlingTimerCompleted(
                    self.manager.state.mission_id,
                    action.robot_id,
                    action.package_id,
                    action.handling_type,
                )
            )

        timer_ref["timer"] = self.create_timer(action.seconds, on_timer)
        self.handling_timers.append(timer_ref["timer"])

    def _handle_event(self, event) -> None:
        self._record_event(event)
        self._dispatch_actions(self.manager.handle_event(event))

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
            serialize_mission_state(
                self.manager,
                self.bridge,
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
