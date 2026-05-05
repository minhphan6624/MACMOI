import json
import unittest
from types import SimpleNamespace

from mrd_mission_manager.actions import DispatchTask
from mrd_mission_manager.events import (
    DownstreamLegCompleted,
    DownstreamPickupCompleted,
    MissionStarted,
    RobotArrivedAtStaging,
    UpstreamLegCompleted,
)
from mrd_mission_manager.mission_manager import MissionManager
from mrd_mission_manager.mission_state import MissionStatus, TaskSegment
from mrd_mission_manager.rmf_bridge import MissionBridgeConfig, RmfMissionBridge


def success_response(task_id):
    return json.dumps(
        {
            "success": True,
            "state": {
                "booking": {
                    "id": task_id,
                }
            },
        }
    )


class TestRmfMissionBridge(unittest.TestCase):
    def test_dispatch_payload_uses_robot_task_patrol_request(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)

        payload = bridge.build_payload(
            DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)
        )

        self.assertEqual(payload["type"], "robot_task_request")
        self.assertEqual(payload["robot"], "tb3_1")
        self.assertEqual(payload["fleet"], "tb3_lab")
        self.assertEqual(payload["request"]["category"], "patrol")
        self.assertEqual(payload["request"]["description"]["places"], ["wp1", "wp2"])
        self.assertIn("mission_id=m1", payload["request"]["labels"])
        self.assertIn("package_id=P1", payload["request"]["labels"])
        self.assertIn("segment=source_to_staging", payload["request"]["labels"])

    def test_successful_response_records_task_context(self):
        published = []
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager, publish_request=lambda *args: published.append(args))
        action = DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)

        request_id = bridge.submit_action(action)
        task_id = bridge.handle_api_response(request_id, success_response("task_1"))

        self.assertEqual(task_id, "task_1")
        self.assertEqual(len(published), 1)
        self.assertEqual(manager.state.robots["tb3_1"].active_task_id, "task_1")
        self.assertEqual(bridge.task_context_by_id["task_1"].package_id, "P1")
        self.assertEqual(
            bridge.task_context_by_id["task_1"].segment,
            TaskSegment.SOURCE_TO_STAGING,
        )

    def test_failed_response_does_not_record_dispatch(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)
        action = DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)

        request_id = bridge.submit_action(action)
        task_id = bridge.handle_api_response(
            request_id,
            json.dumps({"success": False, "errors": [{"detail": "failed"}]}),
        )

        self.assertIsNone(task_id)
        self.assertEqual(bridge.task_context_by_id, {})
        self.assertIsNone(manager.state.robots["tb3_1"].active_task_id)

    def test_ack_response_does_not_consume_pending_request(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)
        action = DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)
        request_id = bridge.submit_action(action)
        ack = SimpleNamespace(
            request_id=request_id,
            json_msg="{}",
            type=1,
            TYPE_RESPONDING=2,
        )

        task_id = bridge.handle_api_response_msg(ack)

        self.assertIsNone(task_id)
        self.assertIn(request_id, bridge.pending_actions)

    def test_completed_task_maps_to_mission_events(self):
        cases = [
            (TaskSegment.SOURCE_TO_STAGING, RobotArrivedAtStaging),
            (TaskSegment.STAGING_TO_TRANSFER, UpstreamLegCompleted),
            (TaskSegment.HOME_TO_TRANSFER, DownstreamPickupCompleted),
            (TaskSegment.TRANSFER_TO_DESTINATION, DownstreamLegCompleted),
        ]

        for segment, event_type in cases:
            manager = MissionManager.create("m1", 1)
            bridge = RmfMissionBridge(manager)
            action = DispatchTask("tb3_1", "P1", segment)
            if segment in (
                TaskSegment.HOME_TO_TRANSFER,
                TaskSegment.TRANSFER_TO_DESTINATION,
            ):
                action = DispatchTask("tb3_2", "P1", segment)
            request_id = bridge.submit_action(action)
            bridge.handle_api_response(request_id, success_response(f"{segment.value}_id"))

            event = bridge.event_from_completed_task(f"{segment.value}_id")

            self.assertIsInstance(event, event_type)

    def test_duplicate_completion_emits_no_second_event(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)
        action = DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)
        request_id = bridge.submit_action(action)
        bridge.handle_api_response(request_id, success_response("task_1"))

        first = bridge.event_from_completed_task("task_1")
        second = bridge.event_from_completed_task("task_1")

        self.assertIsInstance(first, RobotArrivedAtStaging)
        self.assertIsNone(second)

    def test_task_summary_completion_advances_mission(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)
        actions = manager.handle_event(MissionStarted("m1"))

        request_id = bridge.submit_action(actions[0])
        bridge.handle_api_response(request_id, success_response("task_1"))
        task_summary = SimpleNamespace(task_id="task_1", state=2, STATE_COMPLETED=2)
        next_actions = bridge.handle_task_state_update(task_summary)

        self.assertEqual(
            next_actions,
            [DispatchTask("tb3_1", "P1", TaskSegment.STAGING_TO_TRANSFER)],
        )

    def test_custom_robot_names_are_used_by_manager_and_bridge(self):
        manager = MissionManager.create("m1", 1, "upstream_bot", "downstream_bot")
        bridge = RmfMissionBridge(
            manager,
            MissionBridgeConfig(
                upstream_robot="upstream_bot",
                downstream_robot="downstream_bot",
                upstream_home_waypoint="up_home",
                downstream_home_waypoint="down_home",
            ),
        )

        actions = manager.handle_event(MissionStarted("m1"))
        payload = bridge.build_payload(actions[0])

        self.assertEqual(
            actions,
            [
                DispatchTask(
                    "upstream_bot",
                    "P1",
                    TaskSegment.SOURCE_TO_STAGING,
                )
            ],
        )
        self.assertEqual(payload["robot"], "upstream_bot")
        self.assertEqual(bridge.places_for("downstream_bot", TaskSegment.HOME), ["down_home"])

    def test_bridge_can_drive_one_package_to_completion(self):
        manager = MissionManager.create("m1", 1)
        bridge = RmfMissionBridge(manager)

        actions = manager.handle_event(MissionStarted("m1"))
        for index, task_id in enumerate(["t1", "t2", "t3", "t4"], start=1):
            dispatch_actions = [
                action for action in actions if isinstance(action, DispatchTask)
            ]
            self.assertTrue(dispatch_actions)
            request_id = bridge.submit_action(dispatch_actions[0])
            bridge.handle_api_response(request_id, success_response(task_id))
            actions = bridge.handle_completed_task(task_id)

        self.assertEqual(manager.state.status, MissionStatus.COMPLETED)
        self.assertEqual(manager.state.delivered_count, 1)


if __name__ == "__main__":
    unittest.main()
