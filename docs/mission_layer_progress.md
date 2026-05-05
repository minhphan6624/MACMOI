# Mission Manager Current State

## Purpose

This document tracks what has been created so far for the mission manager layer and how the current implementation works.

The package now contains:

* a ROS-free Python mission core
* an RMF bridge that builds `robot_task_request` patrol payloads and maps RMF task completion back into mission events
* a ROS 2 node wrapper that publishes/subscribes on RMF task API topics

The Mission API, rmf-web mission tab, persistent storage, fault recovery, and hard pause/cancel/resume of active RMF tasks are still not implemented.

---

## Implemented Package

Location:

```text
rmf_ws/src/mrd_mission_manager/
```

Files:

```text
mrd_mission_manager/
├── __init__.py
├── actions.py
├── events.py
├── mission_manager.py
├── mission_manager_node.py
├── mission_state.py
├── rmf_bridge.py
├── rule_evaluator.py
└── transfer_controller.py

test/
├── test_mission_manager.py
└── test_rmf_bridge.py
```

Package metadata:

```text
package.xml
setup.cfg
setup.py
resource/mrd_mission_manager
```

The package exposes this console script:

```text
mission_manager_node = mrd_mission_manager.mission_manager_node:main
```

Runtime dependencies currently include `rclpy` and `rmf_task_msgs`.

---

## Implemented Responsibilities

### `mission_state.py`

Defines the mission data model:

* mission status
* package status
* robot status
* task segment names
* package records
* transfer-zone state
* robot mission state

Default fixed robot roles:

```text
tb3_1 = upstream robot
tb3_2 = downstream robot
```

`MissionManager.create(...)` can override those robot IDs.

### `events.py`

Defines mission events, which are facts that already happened.

Implemented events:

```text
MissionStarted
RobotBecameIdle
RobotArrivedAtStaging
UpstreamLegCompleted
DownstreamPickupCompleted
DownstreamLegCompleted
OperatorPaused
OperatorResumed
OperatorAborted
```

Each event carries `mission_id`; robot/package/task events also carry the relevant IDs.

### `actions.py`

Defines mission actions, which are commands emitted by the rule evaluator.

Implemented actions:

```text
DispatchTask
SendRobotHome
CompleteMission
```

### `transfer_controller.py`

Owns Zone B helper logic:

* checks whether a robot can enter transfer
* reserves transfer robot occupancy
* releases transfer robot occupancy
* buffers a package at transfer
* releases a package from transfer
* tracks the waiting robot/package at staging X

Current transfer rules:

```text
Upstream robot may enter B if:
  transfer.robot_occupancy is None
  transfer.package_buffer is None
  package_id is not None

Downstream robot may enter B if:
  transfer.robot_occupancy is None
  transfer.package_buffer is not None
```

### `rule_evaluator.py`

Looks at current mission state and returns the next mission actions.

Implemented rules:

* complete mission and send idle robots home
* continue downstream delivery after transfer pickup
* grant upstream transfer entry from staging X into B
* start downstream pickup when a package is buffered at B
* start upstream package movement from source to staging X

Rules emit no actions unless the mission is `RUNNING`, except completion is evaluated while running and changes the mission to `COMPLETED`.

### `mission_manager.py`

Main state-machine coordinator.

Core methods:

```python
MissionManager.create(
    mission_id,
    total_packages,
    upstream_robot="tb3_1",
    downstream_robot="tb3_2",
)
MissionManager.handle_event(event)
MissionManager.record_dispatch(action, task_id)
```

The core event loop is:

```python
def handle_event(event):
    update_state(event)
    actions = evaluate_rules(state)
    return actions
```

`record_dispatch(...)` must be called after RMF accepts a dispatched task. It marks the robot as moving, stores the RMF task ID on the robot, and records the task ID on the package's upstream or downstream side.

### `rmf_bridge.py`

ROS-free bridge logic between mission actions and RMF task data.

Implemented behavior:

* builds RMF `robot_task_request` JSON payloads
* emits patrol tasks with one round and segment-specific waypoint lists
* stores pending request ID to mission action
* parses successful RMF API responses
* calls `MissionManager.record_dispatch(...)` for accepted `DispatchTask` actions
* stores `task_context_by_id`
* ignores RMF API ack messages and only consumes responding messages
* maps completed task IDs back to mission events
* ignores unknown and duplicate task completions
* accepts both dict-like task states and ROS message-like task states in tests

Task segment mapping:

```text
SOURCE_TO_STAGING       -> [source_waypoint, staging_waypoint]
STAGING_TO_TRANSFER     -> [staging_waypoint, transfer_waypoint]
HOME_TO_TRANSFER        -> [robot_home_waypoint, transfer_waypoint]
TRANSFER_TO_DESTINATION -> [transfer_waypoint, destination_waypoint]
HOME                    -> [robot_home_waypoint]
```

Completion mapping:

```text
SOURCE_TO_STAGING       -> RobotArrivedAtStaging
STAGING_TO_TRANSFER     -> UpstreamLegCompleted
HOME_TO_TRANSFER        -> DownstreamPickupCompleted
TRANSFER_TO_DESTINATION -> DownstreamLegCompleted
HOME                    -> RobotBecameIdle
```

### `mission_manager_node.py`

ROS 2 runtime wrapper.

Implemented behavior:

* creates `MissionManager`
* creates `RmfMissionBridge`
* publishes `rmf_task_msgs/msg/ApiRequest` on `task_api_requests`
* subscribes to `rmf_task_msgs/msg/ApiResponse` on `task_api_responses`
* subscribes to `rmf_task_msgs/msg/Tasks` on `task_summaries` by default
* optionally starts the mission with `auto_start=true`
* submits `DispatchTask` and `SendRobotHome` actions through the bridge

ROS parameters and defaults:

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
upstream_home_waypoint = "wp1"
downstream_home_waypoint = "wp2"

task_summaries_topic = "task_summaries"
```

---

## Main Dataflow

Current RMF-connected dataflow:

```text
MissionEvent
        ↓
MissionManager.handle_event()
        ↓
MissionState update
        ↓
rule_evaluator.evaluate_rules()
        ↓
MissionAction list
        ↓
RmfMissionBridge.submit_action()
        ↓
task_api_requests
        ↓
RMF ApiResponse
        ↓
RmfMissionBridge.handle_api_response_msg()
        ↓
MissionManager.record_dispatch()
        ↓
task_summaries completion update
        ↓
RmfMissionBridge.handle_tasks_msg()
        ↓
MissionEvent
```

The mission core remains ROS-free; the ROS node owns topic I/O.

---

## Current One-Package Workflow

Initial state:

```text
mission.status = READY
P1 = AT_SOURCE
tb3_1 = IDLE
tb3_2 = IDLE
transfer.robot_occupancy = None
transfer.package_buffer = None
transfer.waiting_robot = None
transfer.waiting_package = None
```

### 1. Start Mission

Input event:

```text
MissionStarted
```

State update:

```text
mission.status = RUNNING
```

Rule output:

```text
DispatchTask(tb3_1, P1, SOURCE_TO_STAGING)
```

The bridge submits a robot-specific RMF patrol task:

```text
places = [source_waypoint, staging_waypoint]
```

### 2. RMF Accepts Upstream Dispatch

After RMF responds successfully, the bridge calls:

```text
MissionManager.record_dispatch(action, task_id)
```

State update:

```text
tb3_1.active_task_id = task_id
tb3_1.active_package_id = P1
tb3_1.status = MOVING
P1.upstream_task_id = task_id
P1.status = INBOUND_TO_TRANSFER
```

The bridge stores:

```text
task_context_by_id[task_id] = (mission_id, tb3_1, P1, SOURCE_TO_STAGING)
```

### 3. Robot 1 Arrives At Staging

When RMF reports the source-to-staging task completed, the bridge emits:

```text
RobotArrivedAtStaging(tb3_1, P1, task_id)
```

State update:

```text
tb3_1.status = WAITING_AT_STAGING
tb3_1.active_task_id = None
tb3_1.active_package_id = P1
transfer.waiting_robot = tb3_1
transfer.waiting_package = P1
P1.upstream_task_id = None
P1.status = INBOUND_TO_TRANSFER
```

Rule output, if transfer entry is allowed:

```text
DispatchTask(tb3_1, P1, STAGING_TO_TRANSFER)
```

### 4. Robot 1 Completes Transfer Drop-Off

When RMF reports the staging-to-transfer task completed, the bridge emits:

```text
UpstreamLegCompleted(tb3_1, P1, task_id)
```

State update:

```text
P1.status = AT_TRANSFER
P1.upstream_task_id = None
transfer.package_buffer = P1
transfer.robot_occupancy = None
tb3_1.status = IDLE
tb3_1.active_task_id = None
tb3_1.active_package_id = None
```

Rule output:

```text
DispatchTask(tb3_2, P1, HOME_TO_TRANSFER)
```

### 5. Robot 2 Completes Transfer Pickup

When RMF reports the home-to-transfer task completed, the bridge emits:

```text
DownstreamPickupCompleted(tb3_2, P1, task_id)
```

State update:

```text
P1.status = INBOUND_TO_DESTINATION
P1.downstream_task_id = None
transfer.package_buffer = None
transfer.robot_occupancy = None
tb3_2.status = IDLE
tb3_2.active_task_id = None
tb3_2.active_package_id = P1
```

Rule output:

```text
DispatchTask(tb3_2, P1, TRANSFER_TO_DESTINATION)
```

### 6. Robot 2 Completes Final Delivery

When RMF reports the transfer-to-destination task completed, the bridge emits:

```text
DownstreamLegCompleted(tb3_2, P1, task_id)
```

State update:

```text
P1.status = DELIVERED
P1.downstream_task_id = None
delivered_count += 1
tb3_2.status = IDLE
tb3_2.active_task_id = None
tb3_2.active_package_id = None
```

Rule output, if all packages are delivered:

```text
CompleteMission
SendRobotHome(...) for each idle robot
```

`SendRobotHome` is submitted as an RMF patrol task with one home waypoint.

---

## Important Design Notes

Events and actions are deliberately separate:

```text
Events = things that happened
Actions = things the mission manager wants done next
```

The mission core does not publish RMF tasks. It returns actions. The RMF bridge consumes those actions and the ROS node publishes the resulting requests.

Task IDs must be recorded immediately after dispatch succeeds:

```text
package.upstream_task_id or package.downstream_task_id = task_id
robot.active_task_id = task_id
```

This prevents repeated events or repeated rule evaluation from dispatching duplicate work.

---

## Current Test Coverage

Implemented unittest coverage:

* one-package mission completes
* pause blocks new dispatch
* dispatch payload uses `robot_task_request`
* successful RMF response records task context
* failed RMF response does not record dispatch
* ack responses do not consume pending requests
* completed task IDs map to mission events
* duplicate completion emits no second event
* task summary completion advances the mission
* custom robot names are used by the manager and bridge
* bridge can drive one package from start to completion with mocked RMF responses/completions

Verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager python3 -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

---

## Current Limitations

Not implemented yet:

* Mission API
* rmf-web mission tab
* persistent storage
* fault recovery and retry policy for rejected RMF tasks
* hard pause/cancel/resume of active RMF tasks
* Robot 2 proactive staging while Robot 1 is still unloading/occupying transfer B
* simulated package loading/unloading delays
* live-system validation against a running RMF deployment

---

## Deferred Behavior Notes

### Robot 2 Staging While Transfer Is Occupied

Current behavior is safe but passive:

```text
Robot 2 finishes delivery
Robot 1 is still occupying transfer B
No package is ready for pickup yet
Robot 2 stays logically IDLE
```

The mission manager will not dispatch Robot 2 into B while Robot 1 occupies it, but it also does not yet send Robot 2 to staging X to wait near B.

Desired later behavior:

```text
IF Robot 2 is IDLE
AND Robot 1 is occupying or about to occupy transfer B
AND upstream work is expected to produce a package soon
THEN dispatch Robot 2 to staging X
```

Then, once Robot 1 has exited and the package is buffered:

```text
IF Robot 2 is waiting at staging X
AND transfer.package_buffer contains package_id
AND transfer.robot_occupancy is None
THEN dispatch Robot 2 from staging X into transfer B
```

This likely needs either a downstream-specific staging state or a more general waiting-robot model, because Robot 2 may wait at staging without carrying a package.

### Simulated Loading And Unloading Timers

Current behavior treats handling as immediate:

```text
UpstreamLegCompleted
  -> package immediately becomes AT_TRANSFER

DownstreamPickupCompleted
  -> package immediately becomes INBOUND_TO_DESTINATION

DownstreamLegCompleted
  -> package immediately becomes DELIVERED
```

Desired later behavior is a short simulated delay:

```text
robot reaches handling point
  -> robot status becomes LOADING or UNLOADING
  -> start timer for a few seconds
  -> timer completion emits a mission event
  -> package state changes
  -> rule evaluator dispatches next movement
```

Likely additions:

```text
RobotStatus.LOADING
RobotStatus.UNLOADING
StartHandlingTimer action
HandlingTimerCompleted event
```

This should be implemented before the demo if the UI needs to show realistic package handling time.

---

## Next Implementation Steps

1. Validate `mission_manager_node` against a live RMF deployment and confirm topic names, response payloads, and task summary completion fields.
2. Add launch/config files for the mission manager node once the demo waypoint names are final.
3. Add rejected-task retry or operator-visible failure handling.
4. Add Mission API endpoints.
5. Add rmf-web mission tab.
