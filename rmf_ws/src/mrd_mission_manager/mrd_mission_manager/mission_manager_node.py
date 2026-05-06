import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy
from rclpy.qos import HistoryPolicy
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from rmf_task_msgs.msg import ApiRequest, ApiResponse, Tasks

from .actions import DispatchTask, PositionRobot, SendRobotHome, StartHandlingTimer
from .events import HandlingTimerCompleted, MissionStarted
from .mission_manager import MissionManager
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

        mission_id = self.get_parameter("mission_id").value
        total_packages = self.get_parameter("total_packages").value
        upstream_robot = self.get_parameter("upstream_robot").value
        downstream_robot = self.get_parameter("downstream_robot").value
        self.manager = MissionManager.create(
            mission_id,
            total_packages,
            upstream_robot=upstream_robot,
            downstream_robot=downstream_robot,
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
            Tasks,
            self.get_parameter("task_summaries_topic").value,
            self._handle_task_summaries,
            10,
        )

        self.bridge = RmfMissionBridge(
            self.manager,
            MissionBridgeConfig(
                fleet_name=self.get_parameter("fleet_name").value,
                upstream_robot=upstream_robot,
                downstream_robot=downstream_robot,
                source_waypoint=self.get_parameter("source_waypoint").value,
                staging_waypoint=self.get_parameter("staging_waypoint").value,
                transfer_waypoint=self.get_parameter("transfer_waypoint").value,
                destination_waypoint=self.get_parameter("destination_waypoint").value,
                upstream_home_waypoint=self.get_parameter("upstream_home_waypoint").value,
                downstream_home_waypoint=self.get_parameter(
                    "downstream_home_waypoint"
                ).value,
            ),
            publish_request=self._publish_api_request,
            logger=self.get_logger(),
        )
        self.handling_timers = []

        if self.get_parameter("auto_start").value:
            self._dispatch_actions(self.manager.handle_event(MissionStarted(mission_id)))

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

    def _handle_task_summaries(self, msg: Tasks) -> None:
        self._dispatch_actions(self.bridge.handle_tasks_msg(msg))

    def _dispatch_actions(self, actions) -> None:
        for action in actions:
            if isinstance(action, (DispatchTask, PositionRobot, SendRobotHome)):
                self.bridge.submit_action(action)
            elif isinstance(action, StartHandlingTimer):
                self._start_handling_timer(action)
            else:
                self.get_logger().info(f"Mission action: {action}")

    def _start_handling_timer(self, action: StartHandlingTimer) -> None:
        timer_ref = {}

        def on_timer():
            timer_ref["timer"].cancel()
            self._dispatch_actions(
                self.manager.handle_event(
                    HandlingTimerCompleted(
                        self.manager.state.mission_id,
                        action.robot_id,
                        action.package_id,
                        action.handling_type,
                    )
                )
            )

        timer_ref["timer"] = self.create_timer(action.seconds, on_timer)
        self.handling_timers.append(timer_ref["timer"])


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
