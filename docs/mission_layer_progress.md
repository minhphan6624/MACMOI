# Mission Layer Current Mechanism

This document describes how the current `mrd_mission_manager` package works. It is the implementation reference for the mission layer as it exists now.

The current mission is a fixed two-robot package handoff:

```text
source A -> transfer B -> destination C

Robot 1: upstream, source A -> transfer B
Robot 2: downstream, transfer B -> destination C
```

Zone X is a shared staging waypoint near transfer B. It is used as a waiting/repositioning location when a robot cannot enter B yet. Home waypoints are also configured per robot and are used for mission completion and default positioning routes.

---

## Package Layout

```text
rmf_ws/src/mrd_mission_manager/
├── mrd_mission_manager/
│   ├── actions.py
│   ├── events.py
│   ├── mission_manager.py
│   ├── mission_manager_node.py
│   ├── mission_state.py
│   ├── rmf_bridge.py
│   ├── rule_evaluator.py
│   └── transfer_controller.py
└── test/
    ├── test_mission_manager.py
    └── test_rmf_bridge.py
```

The ROS entrypoint is:

```text
mission_manager_node = mrd_mission_manager.mission_manager_node:main
```

The package has three layers:

```text
Mission core:
  plain Python state machine and rules, no ROS imports

RMF bridge:
  converts mission actions to RMF task API payloads
  converts RMF task completions back to mission events

ROS node:
  owns ROS publishers/subscribers and timers
  connects the mission core/bridge to a running RMF deployment
```

---

## Core Concepts

### Events

Events are facts that already happened. They enter `MissionManager.handle_event(...)`.

Examples:

```text
RMF says a movement task completed
  -> mission event

5 second loading timer expires
  -> mission event

operator starts/pauses/resumes/aborts mission
  -> mission event
```

Implemented events:

```text
MissionStarted
RobotBecameIdle
RobotArrivedAtStaging
DownstreamRobotArrivedAtStaging
UpstreamLegCompleted
DownstreamPickupCompleted
DownstreamLegCompleted
HandlingTimerCompleted
OperatorPaused
OperatorResumed
OperatorAborted
```

### Actions

Actions are commands emitted by the mission layer.

The mission manager does not directly publish ROS messages. It emits actions, and the ROS node decides how to execute those actions.

Implemented actions:

```text
DispatchTask          package-related RMF movement
PositionRobot         package-free robot repositioning
StartHandlingTimer    5 second mission-layer load/unload timer
SendRobotHome         send robot to configured home waypoint
CompleteMission       mark mission completion to external consumers
```

The distinction matters:

```text
DispatchTask = package work
PositionRobot = move robot without assigning a package
StartHandlingTimer = simulate package handling time
```

This separation keeps package state changes from being hidden inside RMF callbacks. The mission core decides what should happen next; the bridge/node only execute those decisions.

---

## State Model

### Mission Status

```text
CREATED
READY
RUNNING
PAUSED
COMPLETED
ABORTED
```

Rules only dispatch new work while the mission is `RUNNING`.

### Package Status

```text
AT_SOURCE
INBOUND_TO_TRANSFER
AT_TRANSFER
INBOUND_TO_DESTINATION
DELIVERED
```

Each package tracks upstream/downstream RMF task IDs to avoid duplicate dispatch.

### Robot Status

```text
IDLE
MOVING
LOADING
UNLOADING
WAITING_AT_STAGING
RETURNING
```

### Robot Location

The mission layer also tracks a logical location:

```text
SOURCE
STAGING
TRANSFER
DESTINATION
HOME
```

This is not a full localization system. It is mission-level context used to choose routes such as `DESTINATION_TO_TRANSFER` instead of `HOME_TO_TRANSFER`.

This location is updated only when mission-relevant tasks complete. It should not be treated as a substitute for robot pose, navigation state, or RMF traffic state.

### Transfer Zone State

```text
robot_occupancy
package_buffer
waiting_robot
waiting_package
```

Current transfer rules:

```text
Robot 1 may enter B if:
  robot_occupancy is None
  package_buffer is None
  package_id is not None

Robot 2 may enter B if:
  robot_occupancy is None
  package_buffer is not None
```

Only Robot 1 uses `waiting_robot/waiting_package` because it waits at staging while already associated with a package. Robot 2 staging is package-free and is represented by robot status/location instead.

---

## RMF Task Segments

In this package, a segment is a named movement leg that the mission layer can request.

Examples:

```text
SOURCE_TO_TRANSFER means "send the selected robot from source A to transfer B"
TRANSFER_TO_DESTINATION means "send Robot 2 from transfer B to destination C"
HOME_TO_STAGING means "reposition a robot from its configured home waypoint to staging X"
```

A segment is not itself an RMF task. It is mission-layer vocabulary. `rmf_bridge.py` translates each segment into an RMF `robot_task_request` patrol payload with a concrete waypoint list.

Current `TaskSegment` values:

```text
SOURCE_TO_TRANSFER
SOURCE_TO_STAGING
STAGING_TO_TRANSFER
HOME_TO_TRANSFER
DESTINATION_TO_TRANSFER
HOME_TO_STAGING
DESTINATION_TO_STAGING
TRANSFER_TO_DESTINATION
HOME
```

Waypoint mapping in `rmf_bridge.py`:

```text
SOURCE_TO_TRANSFER       -> [source_waypoint, transfer_waypoint]
SOURCE_TO_STAGING        -> [source_waypoint, staging_waypoint]
STAGING_TO_TRANSFER      -> [staging_waypoint, transfer_waypoint]
HOME_TO_TRANSFER         -> [robot_home_waypoint, transfer_waypoint]
DESTINATION_TO_TRANSFER  -> [destination_waypoint, transfer_waypoint]
HOME_TO_STAGING          -> [robot_home_waypoint, staging_waypoint]
DESTINATION_TO_STAGING   -> [destination_waypoint, staging_waypoint]
TRANSFER_TO_DESTINATION  -> [transfer_waypoint, destination_waypoint]
HOME                     -> [robot_home_waypoint]
```

There is currently one shared `staging_waypoint` parameter. There are separate home waypoint parameters:

```text
upstream_home_waypoint
downstream_home_waypoint
```

Home waypoints can be distinct or point to the same physical waypoint.

The same segment can have different mission meaning depending on the robot/context. For example, `STAGING_TO_TRANSFER` is used by Robot 1 to drop off a package and by Robot 2 to pick up a package from transfer. The RMF bridge maps completion back to the right event using the robot ID and stored task context.

---

## Runtime Dataflow

`mission_manager_node.py` is the runtime adapter. It is responsible for:

```text
publishing ApiRequest messages to task_api_requests
subscribing to ApiResponse messages from task_api_responses
subscribing to Tasks messages from task_summaries
starting ROS timers for StartHandlingTimer actions
feeding timer completions and RMF completions back into MissionManager
```

It does not contain the mission rules. The rules remain in `rule_evaluator.py`.

```text
Mission event
  -> MissionManager.handle_event()
  -> state transition
  -> rule_evaluator.evaluate_rules()
  -> actions
  -> mission_manager_node dispatches actions
```

Movement actions:

```text
DispatchTask / PositionRobot
  -> RmfMissionBridge.submit_action()
  -> task_api_requests
  -> task_api_responses
  -> record_dispatch() or record_position_dispatch()
  -> task_summaries completion
  -> bridge maps task ID back to mission event
```

Handling actions:

```text
StartHandlingTimer
  -> mission_manager_node creates a ROS timer
  -> timer fires after 5 seconds
  -> HandlingTimerCompleted event
  -> state update
  -> evaluate rules again
```

The mission core remains ROS-free. ROS topic I/O and ROS timers live in `mission_manager_node.py`.

`rmf_bridge.py` is intentionally ROS-free as well. It works with plain Python objects and injected publish callbacks, which makes it testable without a running ROS graph.

---

## Rule Evaluator

`rule_evaluator.py` is the mission decision layer. It reads the current state and returns actions. It does not talk to RMF directly.

The evaluator runs these checks while the mission is `RUNNING`:

1. Complete mission if all packages are delivered.
2. Continue downstream delivery after Robot 2 has loaded at transfer.
3. Grant Robot 1 entry from staging into transfer.
4. Start Robot 2 pickup if a package is buffered at transfer.
5. Reposition Robot 2 to staging if it is idle and waiting for future transfer work.
6. Start or continue Robot 1 upstream package work.

Important behavior:

```text
Robot 1 does not always go through staging.
If B is available, Robot 1 goes source -> transfer directly.
If B is blocked, Robot 1 goes source -> staging, then staging -> transfer.
```

Robot 2 behavior:

```text
If package is ready at B and B is free:
  Robot 2 goes to B from current logical position.

If Robot 2 is at destination and package is ready at B:
  use DESTINATION_TO_TRANSFER.

If Robot 2 has no package and B is not ready:
  PositionRobot sends it to staging.
```

The rule order matters because some rules reserve transfer occupancy before later rules run. This prevents both robots from being dispatched into B during the same evaluation pass.

---

## Current One-Package Flow

### 1. Mission Starts

Input:

```text
MissionStarted
```

State:

```text
mission.status = RUNNING
```

Typical rule output:

```text
StartHandlingTimer(tb3_1, P1, source_load, 5s)
PositionRobot(tb3_2, HOME_TO_STAGING)
```

Robot 1 begins simulated source loading. Robot 2 may move to staging to wait near transfer.

### 2. Robot 1 Finishes Source Loading

Input:

```text
HandlingTimerCompleted(tb3_1, P1, source_load)
```

State:

```text
tb3_1.status = IDLE
tb3_1.active_package_id = P1
tb3_1.location = SOURCE
```

If transfer B is free, rule output:

```text
DispatchTask(tb3_1, P1, SOURCE_TO_TRANSFER)
```

If transfer B is blocked, rule output:

```text
DispatchTask(tb3_1, P1, SOURCE_TO_STAGING)
```

### 3A. Robot 1 Goes Directly To Transfer

After RMF accepts `SOURCE_TO_TRANSFER`, `record_dispatch(...)` marks Robot 1 as moving and records the upstream task ID.

When RMF reports completion, the bridge emits:

```text
UpstreamLegCompleted(tb3_1, P1, task_id)
```

State:

```text
tb3_1.status = UNLOADING
tb3_1.location = TRANSFER
P1.upstream_task_id = None
```

Action:

```text
StartHandlingTimer(tb3_1, P1, transfer_unload, 5s)
```

### 3B. Robot 1 Uses Staging

If Robot 1 was sent `SOURCE_TO_STAGING`, completion maps to:

```text
RobotArrivedAtStaging(tb3_1, P1, task_id)
```

State:

```text
tb3_1.status = WAITING_AT_STAGING
tb3_1.location = STAGING
tb3_1.active_package_id = P1
transfer.waiting_robot = tb3_1
transfer.waiting_package = P1
```

When B becomes available, the evaluator emits:

```text
DispatchTask(tb3_1, P1, STAGING_TO_TRANSFER)
```

Completion then follows the same `UpstreamLegCompleted -> transfer_unload timer` path.

### 4. Robot 1 Finishes Transfer Unloading

Input:

```text
HandlingTimerCompleted(tb3_1, P1, transfer_unload)
```

State:

```text
P1.status = AT_TRANSFER
transfer.package_buffer = P1
transfer.robot_occupancy = None
tb3_1.status = IDLE
tb3_1.active_package_id = None
tb3_1.location = TRANSFER
```

If Robot 2 is waiting at staging, rule output:

```text
DispatchTask(tb3_2, P1, STAGING_TO_TRANSFER)
```

Otherwise Robot 2 may be dispatched from home or destination:

```text
DispatchTask(tb3_2, P1, HOME_TO_TRANSFER)
DispatchTask(tb3_2, P1, DESTINATION_TO_TRANSFER)
```

### 5. Robot 2 Arrives At Transfer And Loads

Completion of Robot 2's transfer-entry task maps to:

```text
DownstreamPickupCompleted(tb3_2, P1, task_id)
```

State:

```text
tb3_2.status = LOADING
tb3_2.location = TRANSFER
tb3_2.active_package_id = P1
P1.downstream_task_id = None
```

Action:

```text
StartHandlingTimer(tb3_2, P1, transfer_load, 5s)
```

### 6. Robot 2 Finishes Transfer Loading

Input:

```text
HandlingTimerCompleted(tb3_2, P1, transfer_load)
```

State:

```text
P1.status = INBOUND_TO_DESTINATION
transfer.package_buffer = None
transfer.robot_occupancy = None
tb3_2.status = IDLE
tb3_2.active_package_id = P1
tb3_2.location = TRANSFER
```

Rule output:

```text
DispatchTask(tb3_2, P1, TRANSFER_TO_DESTINATION)
```

### 7. Robot 2 Arrives At Destination And Unloads

Completion maps to:

```text
DownstreamLegCompleted(tb3_2, P1, task_id)
```

State:

```text
tb3_2.status = UNLOADING
tb3_2.location = DESTINATION
tb3_2.active_package_id = P1
P1.downstream_task_id = None
```

Action:

```text
StartHandlingTimer(tb3_2, P1, destination_unload, 5s)
```

### 8. Destination Unload Completes

Input:

```text
HandlingTimerCompleted(tb3_2, P1, destination_unload)
```

State:

```text
P1.status = DELIVERED
delivered_count += 1
tb3_2.status = IDLE
tb3_2.active_package_id = None
tb3_2.location = DESTINATION
```

If all packages are delivered:

```text
mission.status = COMPLETED
CompleteMission()
SendRobotHome(...) for each idle robot
```

`SendRobotHome` maps to a one-waypoint RMF patrol task using that robot's configured home waypoint.

---

## Multiple Packages

The specification allows up to three active packages:

```text
1 package assigned to Robot 1 upstream
1 package buffered at transfer B
1 package assigned to Robot 2 downstream
```

The current rules support that bounded pipeline:

```text
Robot 1 will not start another transfer drop-off while transfer.package_buffer is occupied.
Robot 2 can deliver one package while Robot 1 starts/loading/moving another package.
Robot 2 can return directly from destination to transfer if another package is ready at B.
```

---

## Completion Behavior

When `delivered_count == total_packages`, the evaluator:

```text
sets mission.status = COMPLETED
emits CompleteMission()
emits SendRobotHome(robot_id) for each robot currently IDLE
```

The RMF bridge maps `SendRobotHome` to:

```text
HOME -> [robot_home_waypoint]
```

This implies the current runtime expects home waypoints to be configured:

```text
upstream_home_waypoint
downstream_home_waypoint
```

They do not need to be special zones in the mission model; they are waypoint names used for return/home behavior.

---

## ROS Node Parameters

Defaults:

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

The current implementation has one shared staging waypoint and one home waypoint setting per robot.

---

## Test Coverage

Current tests cover:

```text
one-package timer-driven mission completion
pause blocks new dispatch
Robot 1 direct source-to-transfer when B is available
Robot 1 source-to-staging fallback when B is occupied
Robot 2 direct destination-to-transfer return
RMF payload generation
successful and failed RMF API responses
ack responses not consuming pending requests
task completion to mission event mapping
duplicate task completion suppression
custom robot names and home waypoints
bridge-driven one-package completion
```

Verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager python3 -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

---

## Current Limitations

Still not implemented:

```text
Mission API
rmf-web mission tab
persistent storage
launch/config file for demo deployment
fault recovery and retry policy for rejected RMF tasks
operator-visible failure state
hard pause/cancel/resume of active RMF tasks
live-system validation against a running RMF deployment
separate upstream/downstream staging waypoints
```

The current package is still a fixed two-robot mission layer, not a general multi-robot planner.

---

## Next Steps

1. Validate `mission_manager_node` against a live RMF deployment.
2. Confirm RMF topic names, response JSON, and task summary completion fields.
3. Add launch/config files for final demo waypoint names.
4. Add rejected-task retry or operator-visible failure handling.
5. Add Mission API endpoints and the rmf-web mission tab. See [mission_web_development_plan.md](mission_web_development_plan.md) for the detailed web/API plan.
