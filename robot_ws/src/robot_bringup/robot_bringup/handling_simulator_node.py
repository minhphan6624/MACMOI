import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from turtlebot3_msgs.srv import Sound

SOUND_BUTTON1 = 4
SOUND_BUTTON2 = 5

class HandlingSimulatorNode(Node):
    def __init__(self):
        super().__init__("handling_simulator")

        # Params
        self.declare_parameter("robot_id", "")
        self.declare_parameter("mission_id", "")
        self.declare_parameter("handling_duration_sec", 5.0)
        self.declare_parameter("sound_service", "sound")

        # Pubs, subs and clients
        self.result_pub = self.create_publisher(String,"mission_execution_results",10,)
        
        self.create_subscription(String, "mission_execution_commands",self._handle_command,10,)
        
        sound_service = self.get_parameter("sound_service").value
        self.sound_client = self.create_client(Sound, sound_service)

        # Extract param values
        self.robot_id = self.get_parameter("robot_id").value
        self.mission_id = self.get_parameter("mission_id").value
        self.handling_duration_sec = float(self.get_parameter("handling_duration_sec").value)

        self.active_timers = {}
        self.completed_command_ids = set()
        self.sound_unavailable_logged = False

        self.get_logger().info(f"Handling simulator ready for robot_id={self.robot_id}")
        self.get_logger().info(
            f"Sound cues will use {self.sound_client.service_name}"
        )

    def _handle_command(self, msg: String) -> None:
        try:
            command = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning(f"Invalid execution command JSON: {msg.data}")
            return

        # ----- Validation -----
        if command.get("command_type") != "handle_item":
            return
        
        if command.get("robot_id") != self.robot_id:
            return
        
        if self.mission_id and command.get("mission_id") != self.mission_id:
            return

        command_id = command.get("command_id")
        mission_id = command.get("mission_id")
        if not isinstance(command_id, str) or not isinstance(mission_id, str):
            self.get_logger().warning(f"Invalid handling command: {command}")
            return
        if command_id in self.active_timers or command_id in self.completed_command_ids:
            return

        # ----- Handling starts -----
        self.get_logger().info(
            f"Simulating {command.get('handling_type')} for item "
            f"{command.get('item_id')} on {self.robot_id}"
        )
        self._play_sound(SOUND_BUTTON1)

        timer_ref = {}

        def on_timer():
            timer_ref["timer"].cancel()
            self.active_timers.pop(command_id, None)
            self.completed_command_ids.add(command_id)
            self._play_sound(SOUND_BUTTON2)
            self._publish_result(command)

        timer_ref["timer"] = self.create_timer(self.handling_duration_sec, on_timer)
        self.active_timers[command_id] = timer_ref["timer"]

    def _play_sound(self, value: int) -> None:
        if not self.sound_client.wait_for_service(timeout_sec=1.0):
            if not self.sound_unavailable_logged:
                self.get_logger().warning(
                    f"Sound service {self.sound_client.service_name} is unavailable"
                )
                self.sound_unavailable_logged = True
            return

        self.sound_unavailable_logged = False
        request = Sound.Request()
        request.value = value
        future = self.sound_client.call_async(request)
        future.add_done_callback(self._handle_sound_response)

    def _handle_sound_response(self, future) -> None:
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().warning(f"Sound request failed: {exc}")
            return

        if not response.success:
            self.get_logger().warning(f"Sound request rejected: {response.message}")
            return

        self.get_logger().info("Sound cue accepted")

    def _publish_result(self, command: dict) -> None:
        msg = String()
        msg.data = json.dumps(
            {
                "mission_id": command["mission_id"],
                "command_id": command["command_id"],
                "robot_id": self.robot_id,
                "item_id": command.get("item_id"),
                "handling_type": command.get("handling_type"),
                "status": "SUCCEEDED",
                "source": "robot_handling_simulator",
            }
        )
        self.result_pub.publish(msg)
        self.get_logger().info(
            f"Published handling result for {command['command_id']}"
        )


def main(args=None):
    rclpy.init(args=args)
    node = HandlingSimulatorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
