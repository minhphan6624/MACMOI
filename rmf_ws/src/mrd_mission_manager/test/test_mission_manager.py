import unittest

from mrd_mission_manager.actions import CompleteMission
from mrd_mission_manager.actions import DispatchTask
from mrd_mission_manager.events import DownstreamLegCompleted
from mrd_mission_manager.events import DownstreamPickupCompleted
from mrd_mission_manager.events import MissionStarted
from mrd_mission_manager.events import RobotArrivedAtStaging
from mrd_mission_manager.events import UpstreamLegCompleted
from mrd_mission_manager.mission_manager import MissionManager
from mrd_mission_manager.mission_state import MissionStatus
from mrd_mission_manager.mission_state import PackageStatus
from mrd_mission_manager.mission_state import TaskSegment


def dispatch(manager, action, task_id):
    manager.record_dispatch(action, task_id)
    return task_id


class TestMissionManager(unittest.TestCase):
    def test_one_package_mission_completes(self):
        manager = MissionManager.create("m1", 1)

        actions = manager.handle_event(MissionStarted("m1"))
        self.assertEqual(
            actions,
            [DispatchTask("tb3_1", "P1", TaskSegment.SOURCE_TO_STAGING)],
        )

        dispatch(manager, actions[0], "t1")
        actions = manager.handle_event(
            RobotArrivedAtStaging("m1", "tb3_1", "P1", "t1")
        )
        self.assertEqual(
            actions,
            [DispatchTask("tb3_1", "P1", TaskSegment.STAGING_TO_TRANSFER)],
        )

        dispatch(manager, actions[0], "t2")
        actions = manager.handle_event(UpstreamLegCompleted("m1", "tb3_1", "P1", "t2"))
        self.assertEqual(
            actions,
            [DispatchTask("tb3_2", "P1", TaskSegment.HOME_TO_TRANSFER)],
        )
        self.assertEqual(manager.state.transfer.package_buffer, "P1")

        dispatch(manager, actions[0], "t3")
        actions = manager.handle_event(
            DownstreamPickupCompleted("m1", "tb3_2", "P1", "t3")
        )
        self.assertIn(
            DispatchTask("tb3_2", "P1", TaskSegment.TRANSFER_TO_DESTINATION),
            actions,
        )
        self.assertIsNone(manager.state.transfer.package_buffer)

        dispatch(
            manager,
            DispatchTask("tb3_2", "P1", TaskSegment.TRANSFER_TO_DESTINATION),
            "t4",
        )
        actions = manager.handle_event(
            DownstreamLegCompleted("m1", "tb3_2", "P1", "t4")
        )

        self.assertEqual(manager.state.packages["P1"].status, PackageStatus.DELIVERED)
        self.assertEqual(manager.state.delivered_count, 1)
        self.assertEqual(manager.state.status, MissionStatus.COMPLETED)
        self.assertTrue(any(isinstance(action, CompleteMission) for action in actions))

    def test_pause_blocks_new_dispatch(self):
        manager = MissionManager.create("m1", 1)
        manager.handle_event(MissionStarted("m1"))
        manager.state.status = MissionStatus.PAUSED

        actions = manager.handle_event(
            RobotArrivedAtStaging("m1", "tb3_1", "P1", "t1")
        )

        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
