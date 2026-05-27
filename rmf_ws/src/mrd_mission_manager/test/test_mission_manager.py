import unittest

from mrd_mission_manager.actions import (
    CompleteMission,
    DispatchTask,
    PositionRobot,
    StartHandlingTimer,
)
from mrd_mission_manager.events import (
    DownstreamLegCompleted,
    DownstreamRobotArrivedAtStaging,
    DownstreamPickupCompleted,
    HandlingTimerCompleted,
    MissionStarted,
    RobotArrivedAtStaging,
    UpstreamLegCompleted,
)
from mrd_mission_manager.mission_manager import MissionManager
from mrd_mission_manager.mission_state import (
    MissionStatus,
    PackageStatus,
    RobotLocation,
    TaskSegment,
)


def dispatch(manager, action, task_id):
    manager.record_dispatch(action, task_id)
    return task_id


class TestMissionManager(unittest.TestCase):
    def test_one_package_mission_completes(self):
        manager = MissionManager.create("m1", 1)

        actions = manager.handle_event(MissionStarted("m1"))
        self.assertIn(
            PositionRobot("tb3_2", TaskSegment.HOME_TO_STAGING),
            actions,
        )
        self.assertIn(
            StartHandlingTimer("tb3_1", "P1", "source_load"),
            actions,
        )

        position_action = next(
            action for action in actions if isinstance(action, PositionRobot)
        )
        manager.record_position_dispatch(position_action, "s1")
        self.assertEqual(
            manager.handle_event(DownstreamRobotArrivedAtStaging("m1", "tb3_2", "s1")),
            [],
        )

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_1", "P1", "source_load")
        )
        self.assertEqual(
            actions,
            [DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_TRANSFER)],
        )

        dispatch(manager, actions[0], "t1")
        actions = manager.handle_event(UpstreamLegCompleted("m1", "tb3_1", "P1", "t1"))
        self.assertEqual(
            actions,
            [StartHandlingTimer("tb3_1", "P1", "transfer_unload")],
        )

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_1", "P1", "transfer_unload")
        )
        self.assertEqual(
            actions,
            [DispatchTask("tb3_2", "P1", TaskSegment.STAGING_TO_TRANSFER)],
        )
        self.assertEqual(manager.state.transfer.package_buffer, "P1")

        dispatch(manager, actions[0], "t2")
        actions = manager.handle_event(
            DownstreamPickupCompleted("m1", "tb3_2", "P1", "t2")
        )
        self.assertEqual(
            actions,
            [StartHandlingTimer("tb3_2", "P1", "transfer_load")],
        )

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_2", "P1", "transfer_load")
        )
        self.assertIn(
            DispatchTask("tb3_2", "P1", TaskSegment.TRANSFER_TO_DESTINATION),
            actions,
        )
        self.assertIsNone(manager.state.transfer.package_buffer)

        dispatch(
            manager,
            DispatchTask("tb3_2", "P1", TaskSegment.TRANSFER_TO_DESTINATION),
            "t3",
        )
        actions = manager.handle_event(
            DownstreamLegCompleted("m1", "tb3_2", "P1", "t3")
        )
        self.assertEqual(
            actions,
            [StartHandlingTimer("tb3_2", "P1", "destination_unload")],
        )

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_2", "P1", "destination_unload")
        )

        self.assertEqual(manager.state.packages["P1"].status, PackageStatus.DELIVERED)
        self.assertEqual(manager.state.delivered_count, 1)
        self.assertEqual(manager.state.status, MissionStatus.COMPLETED)
        self.assertTrue(any(isinstance(action, CompleteMission) for action in actions))
        self.assertFalse(any(isinstance(action, DispatchTask) for action in actions))

    def test_pause_blocks_new_dispatch(self):
        manager = MissionManager.create("m1", 1)
        manager.handle_event(MissionStarted("m1"))
        manager.state.status = MissionStatus.PAUSED

        actions = manager.handle_event(
            RobotArrivedAtStaging("m1", "tb3_1", "P1", "t1")
        )

        self.assertEqual(actions, [])

    def test_upstream_uses_staging_when_transfer_is_occupied(self):
        manager = MissionManager.create("m1", 1)
        manager.handle_event(MissionStarted("m1"))
        manager.state.transfer.robot_occupancy = "tb3_2"

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_1", "P1", "source_load")
        )

        self.assertEqual(
            actions,
            [DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)],
        )

    def test_downstream_can_return_directly_from_destination_to_transfer(self):
        manager = MissionManager.create("m1", 2)
        manager.state.status = MissionStatus.RUNNING
        manager.state.transfer.package_buffer = "P2"
        manager.state.packages["P2"].status = PackageStatus.AT_TRANSFER
        manager.state.robots["tb3_2"].location = RobotLocation.DESTINATION

        actions = manager.handle_event(
            HandlingTimerCompleted("m1", "tb3_2", "P1", "destination_unload")
        )

        self.assertIn(
            DispatchTask("tb3_2", "P2", TaskSegment.DESTINATION_TO_TRANSFER),
            actions,
        )


if __name__ == "__main__":
    unittest.main()
