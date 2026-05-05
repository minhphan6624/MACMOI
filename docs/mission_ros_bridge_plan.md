# Mission ROS Bridge Implementation Plan

## Summary

Implement the first ROS-facing bridge inside `rmf_ws/src/mrd_mission_manager` to connect the pure Python mission manager to Open-RMF task execution.

The bridge will:

* consume `DispatchTask` actions from the mission manager
* submit robot-specific RMF patrol tasks through `task_api_requests`
* record returned RMF task IDs with `MissionManager.record_dispatch(...)`
* track RMF task ID to mission context
* translate completed RMF tasks back into mission events
* feed those events into `MissionManager.handle_event(...)`

The mission core remains ROS-free. ROS and RMF-specific behavior lives in the bridge/node layer.

---

## Key Additions

Add `rmf_bridge.py`:

* Build RMF `robot_task_request` JSON payloads.
* Publish requests through an injected callback so the bridge can be unit tested without ROS.
* Parse RMF API responses.
* Store `task_context_by_id`.
* Convert completed task IDs into mission events.
* Ignore unknown or already-processed task IDs.

Add `mission_manager_node.py`:

* Create a ROS 2 node wrapper.
* Instantiate `MissionManager`.
* Instantiate `RmfMissionBridge`.
* Publish `rmf_task_msgs/msg/ApiRequest` on `task_api_requests`.
* Subscribe to `rmf_task_msgs/msg/ApiResponse` on `task_api_responses`.
* Subscribe to `rmf_task_msgs/msg/Tasks` on `task_summaries`.
* Dispatch new actions returned by the mission manager.

Add package metadata:

* Add `rclpy` and `rmf_task_msgs` runtime dependencies.
* Add a console script entry point for the node.

---

## Configuration

Use ROS parameters with defaults:

```text
mission_id = "m1"
total_packages = 1
auto_start = false

fleet_name = "tb3_lab"
upstream_robot = "tb3_1"
downstream_robot = "tb3_2"

source_waypoint = "wp1"
staging_waypoint = "wp2"
transfer_waypoint = "wp3"
destination_waypoint = "wp4"

tb3_1_home_waypoint = "wp1"
tb3_2_home_waypoint = "wp2"
task_summaries_topic = "task_summaries"
```

No building map update is required for this step. These parameters map mission concepts to existing RMF waypoints.

---

## Dispatch Mapping

Use robot-specific task requests because robot roles are fixed.

Payload shape:

```json
{
  "type": "robot_task_request",
  "robot": "tb3_1",
  "fleet": "tb3_lab",
  "request": {
    "category": "patrol",
    "fleet_name": "tb3_lab",
    "description": {
      "places": ["wp1", "wp2"],
      "rounds": 1
    },
    "labels": [
      "mission_id=m1",
      "package_id=P1",
      "segment=source_to_staging"
    ],
    "requester": "mrd_mission_manager"
  }
}
```

Segment mapping:

```text
SOURCE_TO_STAGING:
  robot = tb3_1
  places = [source_waypoint, staging_waypoint]

STAGING_TO_TRANSFER:
  robot = tb3_1
  places = [staging_waypoint, transfer_waypoint]

HOME_TO_TRANSFER:
  robot = tb3_2
  places = [tb3_2_home_waypoint, transfer_waypoint]

TRANSFER_TO_DESTINATION:
  robot = tb3_2
  places = [transfer_waypoint, destination_waypoint]

HOME:
  places = [robot_home_waypoint]
```

When RMF responds successfully:

* extract `task_id` from `response["state"]["booking"]["id"]`
* call `MissionManager.record_dispatch(action, task_id)`
* store `task_context_by_id[task_id]`

If RMF rejects the task:

* log the failure
* do not call `record_dispatch`
* leave mission state unchanged for v1

---

## Completion Translation

When an RMF task reaches completed status, look up its context by task ID and emit:

```text
SOURCE_TO_STAGING
  -> RobotArrivedAtStaging

STAGING_TO_TRANSFER
  -> UpstreamLegCompleted

HOME_TO_TRANSFER
  -> DownstreamPickupCompleted

TRANSFER_TO_DESTINATION
  -> DownstreamLegCompleted

HOME
  -> RobotBecameIdle
```

Track processed completions:

```python
completed_task_ids: set[str]
```

This prevents duplicate RMF task updates from re-emitting the same mission event.

---

## Tests

Add unit tests that do not require a live RMF system:

* `DispatchTask(SOURCE_TO_STAGING)` creates a `robot_task_request` with `places=["wp1", "wp2"]`.
* successful RMF response records task context
* failed RMF response does not record dispatch
* completed task IDs map to the correct mission events
* duplicate completion emits no second event
* bridge can drive one package from start to completion using mocked responses/completions

Verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager python -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

---

## Assumptions

* Use existing RMF waypoints `wp1`, `wp2`, `wp3`, and `wp4`.
* Do not update the building map for this step.
* Use `robot_task_request`, not `dispatch_task_request`.
* Use RMF patrol tasks, not native RMF delivery tasks.
* Keep mission state in memory.
* Do not implement Mission API or rmf-web UI in this step.
* Do not implement hard pause/cancel/resume yet.
