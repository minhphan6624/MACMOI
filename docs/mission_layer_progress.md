# Mission Manager Current State

## Purpose

This document tracks what has been created so far for the mission manager layer and how the current implementation works.

The current implementation is a pure Python mission core. It does not talk to ROS 2, Open-RMF, free_fleet, the Mission API, or rmf-web yet.

---

## Implemented Package

Location:

```text
rmf_ws/src/mrd_mission_manager/
```

Files:

```text
mrd_mission_manager/
├── actions.py
├── events.py
├── mission_manager.py
├── mission_state.py
├── rule_evaluator.py
└── transfer_controller.py

test/
└── test_mission_manager.py
```

Package metadata:

```text
package.xml
setup.cfg
setup.py
resource/mrd_mission_manager
```

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
* `create_mission()`

Current fixed robot roles:

```text
tb3_1 = upstream robot
tb3_2 = downstream robot
```

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
Robot 1 may enter B if:
  transfer.robot_occupancy is None
  transfer.package_buffer is None

Robot 2 may enter B if:
  transfer.robot_occupancy is None
  transfer.package_buffer is not None
```

### `rule_evaluator.py`

Looks at current mission state and returns the next mission actions.

Implemented rules:

* complete mission
* continue downstream delivery
* grant transfer entry from staging X into B
* start downstream pickup
* start upstream package

### `mission_manager.py`

Main state-machine coordinator.

Core methods:

```python
MissionManager.create(mission_id, total_packages)
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

### `test_mission_manager.py`

Current smoke coverage:

* one-package mission completes
* pause blocks new dispatch

Verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager python -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

---

## Main Dataflow

Current test/manual dataflow:

```text
manual/test input
        ↓
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
manual/test record_dispatch()
        ↓
next completion event
```

Future RMF-connected dataflow:

```text
MissionAction
        ↓
RMF Bridge
        ↓
Open-RMF patrol/loop task
        ↓
RMF task ID
        ↓
MissionManager.record_dispatch()
        ↓
RMF task completion update
        ↓
RMF Bridge maps task ID to mission context
        ↓
MissionEvent
        ↓
MissionManager.handle_event()
```

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

### 2. Record Upstream Dispatch

After RMF accepts the task, the caller should call:

```text
record_dispatch(action, task_id)
```

State update:

```text
tb3_1.active_task_id = task_id
tb3_1.active_package_id = P1
tb3_1.status = MOVING
P1.upstream_task_id = task_id
P1.status = INBOUND_TO_TRANSFER
```

### 3. Robot 1 Arrives At Staging

Input event:

```text
RobotArrivedAtStaging(tb3_1, P1, task_id)
```

State update:

```text
tb3_1.status = WAITING_AT_STAGING
tb3_1.active_task_id = None
transfer.waiting_robot = tb3_1
transfer.waiting_package = P1
P1.upstream_task_id = None
```

Rule output, if transfer entry is allowed:

```text
DispatchTask(tb3_1, P1, STAGING_TO_TRANSFER)
```

### 4. Robot 1 Completes Transfer Drop-Off

Input event:

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
```

Rule output:

```text
DispatchTask(tb3_2, P1, HOME_TO_TRANSFER)
```

### 5. Robot 2 Completes Transfer Pickup

Input event:

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
tb3_2.active_package_id = P1
```

Rule output:

```text
DispatchTask(tb3_2, P1, TRANSFER_TO_DESTINATION)
```

### 6. Robot 2 Completes Final Delivery

Input event:

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
SendRobotHome(...)
```

---

## Important Design Notes

Events and actions are deliberately separate:

```text
Events = things that happened
Actions = things the mission manager wants done next
```

The mission manager does not directly submit RMF tasks. It returns `DispatchTask` actions. The future RMF bridge will consume those actions and submit RMF patrol/loop-style tasks.

Task IDs must be recorded immediately after dispatch succeeds:

```text
package.upstream_task_id or package.downstream_task_id = task_id
robot.active_task_id = task_id
```

This prevents repeated events or repeated rule evaluation from dispatching duplicate work.

---

## Current Limitations

Not implemented yet:

* ROS 2 mission manager node
* RMF bridge
* RMF task submission
* RMF task completion subscription/translation
* task-context mapping from RMF task ID to mission context
* Robot 2 proactive staging while Robot 1 is still unloading/occupying transfer B
* simulated package loading/unloading delays
* Mission API
* rmf-web mission tab
* persistent storage
* fault recovery
* hard pause/cancel/resume of active RMF tasks

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

## Next Implementation Step

Build the RMF bridge skeleton.

It should:

1. consume `DispatchTask`
2. submit the correct RMF patrol/loop-style waypoint task
3. receive or store the returned RMF task ID
4. call `MissionManager.record_dispatch(action, task_id)`
5. keep `task_context_by_id`
6. translate RMF task completion updates back into mission events

Example task context:

```python
task_context_by_id = {
    "task_123": {
        "mission_id": "m1",
        "package_id": "P1",
        "robot_id": "tb3_1",
        "segment": "source_to_staging",
    }
}
```
