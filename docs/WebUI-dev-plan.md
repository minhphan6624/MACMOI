# Mission Web/API Development Plan

This document captures the planned web-facing work for the mission layer. It is
intended for the stage after the ROS mission node has been validated against a
live RMF deployment.

The mission web layer should sit above the existing RMF dashboard. It should
show mission progress, transfer-zone bottlenecks, robot involvement, operator
actions, and enough debug state to understand what happened during a run. It
should not replace the full RMF fleet dashboard or become a raw ROS topic
console.

---

## Design Principles

Keep one authority for mission behavior. If the ROS mission manager owns live
mission state, the API backend should observe and command that node rather than
creating a separate mission runtime.

Separate live control from historical storage. The dashboard should observe live
ROS/RMF updates, while the database should store history, audit records, and
artifacts for later analysis.

Route interventions through RMF or the mission manager first. Avoid browser-to-
robot control paths unless the system has an explicit manual-control mode and
recovery workflow.

Expose mission concepts, not raw implementation detail. Operators need to know
what the mission is doing, what is blocked, which robots are involved, and what
actions are available.

---

## 1. Mission State Contract

Add a mission-state serialization layer close to the mission core. This keeps
tests, the API backend, and the frontend aligned around the same state shape.

The state should include:

```text
mission status
total packages
delivered count
remaining count
package statuses
robot statuses
robot logical locations
active package/task IDs
transfer robot occupancy
transfer package buffer
waiting robot/package at staging
recent mission events/actions
```

This should be a stable contract that can initially feed mock UI data and later
feed live API/WebSocket updates without rewriting the dashboard components.

---

## 2. Mission API Backend

Add backend endpoints for mission lifecycle and observation:

```text
POST /missions
POST /missions/{mission_id}/start
POST /missions/{mission_id}/pause
POST /missions/{mission_id}/resume
POST /missions/{mission_id}/abort
GET  /missions/{mission_id}
```

The backend can either run the mission runtime in-process or communicate with
the ROS mission manager node. For this project, prefer keeping one mission
authority. If the ROS node owns the live mission, the API backend should send
commands to that node and expose its state.

---

## 3. Live Updates

The UI should not rely on manual refresh. Add one live update path:

```text
WebSocket updates
Server-Sent Events
short polling
```

The live stream should include mission state changes, recent events, emitted
actions, RMF task IDs, rejected-task messages, and failure messages.

### 3.1. Start With ROS Topic Payload Separation

See also
[`docs/mission-topic-organization.md`](mission-topic-organization.md) for the
mission topic ownership rules.

The first implementation target should be payload separation, not a broad topic
rename. The current flat topic names are already used by the mission node,
execution bridge, runbook commands, and robot-side handling simulator. Renaming
them before the payload contract is clean would create integration churn without
helping the web UI.

Keep the existing compatibility topics initially:

```text
mission_state
mission_commands
mission_execution_commands
mission_execution_results
```

Add these mission-owned observation topics:

```text
mission_debug_state
mission_events
```

Split mission serialization into three outputs:

```text
mission_state
  compact dashboard/operator snapshot

mission_debug_state
  verbose developer snapshot with raw internal state

mission_events
  append-style event stream for timeline, audit, and debugging
```

`mission_state` should be shaped for the dashboard contract, not for raw Python
object inspection. It should include:

```text
mission summary:
  mission ID
  mission name
  status
  phase
  current step
  total steps
  active robot
  current blocker
  next step
  last update timestamp

package summaries:
  package ID
  status
  location
  carried_by

robot mission overlay:
  robot ID
  display label
  mission state
  active mission task
  logical mission location
  mission issue/waiting reason
  active RMF task ID when known

task timeline:
  task ID
  label
  status
  phase
  assigned robot
  pickup/start
  dropoff/goal
  dependencies
  blocked reason
  next expected event

zone/resource summary:
  source/transfer/destination/home/wait zones
  transfer occupancy
  transfer package buffer
  waiting robot/package
  active lease owner

operator summary:
  active command count
  blocked task count
  last event
```

The compact state should receive only `last_event` from mission-node-local
context. Recent event arrays, recent action arrays, active handling command
internals, and RMF adapter maps belong in `mission_debug_state`.

`mission_state` should not include:

```text
raw mission task dataclasses
raw resource objects
raw execution command objects
RMF adapter request maps
completed RMF task ID sets
long recent event/action arrays
active handling command internals
```

Move those fields to `mission_debug_state`. That topic can stay large because
it is for developers, rosbag inspection, and terminal debugging rather than the
primary web UI state path.

`mission_events` should publish one small JSON event at a time. Example events:

```json
{"type":"MissionStarted","mission_id":"m1"}
{"type":"TaskBlocked","task_id":"P1:transfer_to_destination","reason":"PACKAGE_NOT_AVAILABLE"}
{"type":"ExecutionCommandCompleted","command_id":"cmd_3","source":"task_summary"}
{"type":"MissionCompleted","mission_id":"m1"}
```

The web dashboard should eventually assemble its `DashboardData` from multiple
sources:

```text
mission_state:
  mission summary, package state, mission task timeline, transfer/resource state

mission_events:
  event log and timeline history

RMF web/fleet data:
  robot battery, online/offline state, physical position, map/fleet telemetry

API/UI local state:
  selected entity, acknowledged alerts, derived warnings
```

Do not put RMF-owned telemetry such as battery level, exact robot pose, or full
fleet health into `mission_state` just to satisfy the mock dashboard. The
mission layer should expose collaboration semantics; RMF/web should remain the
source for fleet telemetry.

Practical implementation order:

```text
1. Done: add compact `serialize_mission_state(...)`.
2. Done: move the current verbose payload to `serialize_mission_debug_state(...)`.
3. Done: add `mission_debug_state` publisher in the mission node.
4. Done: add `mission_events` publisher and emit events from `_record_event(...)`.
5. Done: keep only `last_event` in `mission_state`; keep full debug context in debug state.
6. Done: update README/runbook echo commands for the new split.
7. Next: add API-server subscriptions and websocket rooms for state/events/debug.
8. Next: replace mock dashboard data with an API-side mapper to the dashboard contract.
9. Later: consider namespacing topics only after the web/API bridge and execution bridge are updated.
```

---

## 4. Mission Dashboard View

The mission tab should answer five operator questions:

```text
What is the mission doing right now?
What is happening at the transfer zone?
What are the robots currently doing?
How far through the package batch are we?
Can the operator intervene?
```

Use compact operational panels:

```text
Mission summary:
  mission ID
  mission state
  total package count
  delivered count
  remaining count
  progress indicator

Transfer zone:
  robot occupancy
  package buffer occupancy
  waiting robot/package
  transfer status: free, blocked, or in use

Robot activity:
  robot status
  logical location
  current leg/current package
  active RMF task ID
  link to RMF robot/task detail

Event timeline:
  package loaded/dropped/picked/delivered
  robot staged/entered transfer
  mission paused/resumed/aborted/completed
  recent RMF task request/response status
```

Initial controls:

```text
create mission
start
pause
resume
abort
```

The proof of concept should stay mission-oriented. Avoid turning this tab into a
manual navigation panel or a debugging console for every ROS topic.

---

## 5. Debug Visibility

Before polishing the UI, expose enough detail to validate behavior:

```text
last emitted action
last consumed event
active RMF task IDs
active handling command
current package assigned to each robot
current transfer occupancy/buffer state
blocked task count
active command count
```

This is important because the mission layer currently has no dedicated UI and
only minimal ROS logs.

---

## 6. Operator Intervention Levels

Operator intervention should be introduced in levels. Each level gives the
operator more control but increases the amount of mission-state reconciliation
needed.

### Level 0: Observe Only

The operator can view robot, task, and mission state but cannot affect the
system.

Examples:

```text
robot location
current RMF task
mission step
blocked/waiting state
battery/status
```

Implementation notes:

```text
connect mission dashboard data to the API/live stream
keep UI components read-only
record no operator command events
```

Complexity: low.

### Level 1: Mission-Level Pause and Resume

The operator pauses mission scheduling, not necessarily the robot's current
physical movement.

Meaning:

```text
do not start new mission tasks
keep current mission state intact
allow current robot actions to finish unless separately interrupted
```

Implementation notes:

```text
add PAUSED / ABORTING / ABORTED mission states
make MissionManager.tick() stop dispatching new work while paused
log pause/resume/abort as operator events
expose pause/resume/abort through the mission API
```

Complexity: low to medium.

### Level 2: Task-Level Intervention

The operator intervenes in the current RMF task rather than directly commanding
the robot hardware.

Examples:

```text
cancel current task
interrupt task
resume interrupted task
kill task
skip phase
rewind phase
```

The RMF web API already exposes task-control endpoints such as:

```text
POST /tasks/cancel_task
POST /tasks/interrupt_task
POST /tasks/resume_task
POST /tasks/kill_task
POST /tasks/skip_phase
POST /tasks/rewind_task
```

Implementation notes:

```text
replace mock mission action handlers with API calls
add confirmation dialogs for destructive actions
only enable actions for valid task states
record who requested each intervention
make the mission manager consume the resulting task state update
```

Complexity: medium.

### Level 3: Robot Availability Control

The operator changes whether RMF may assign work to a robot.

Examples:

```text
decommission robot
recommission robot
stop assigning new tasks to a robot
allow or block idle behavior
```

The RMF web API already supports fleet-level commission control:

```text
POST /fleets/{name}/decommission
POST /fleets/{name}/recommission
```

Implementation notes:

```text
surface existing decommission/recommission behavior in the mission UI
decide whether queued tasks should be cancelled or reassigned
decide whether idle behavior such as return-to-charger is allowed
record the intervention in the mission event log
```

Complexity: medium.

### Level 4: Direct RMF Robot Task

The operator assigns a direct RMF task to a specific robot, such as sending it
to a waypoint.

Examples:

```text
send robot to charger
send robot to staging
send robot to safe waypoint
send robot to inspection point
```

This should still go through RMF, not directly to Nav2. The API already exposes:

```text
POST /tasks/robot_task
```

Implementation notes:

```text
add a controlled "send to waypoint" UI
choose from known map waypoints
interrupt or cancel conflicting mission tasks first
mark robot control mode as operator_override
prevent the mission scheduler from immediately assigning that robot new work
```

Useful state fields:

```text
robot.control_mode: autonomous | operator_override
mission.status: active | paused | operator_intervention
```

Complexity: medium to high.

### Level 5: Mission Recovery Actions

The operator changes mission truth, not just robot execution.

Examples:

```text
retry package pickup
reassign package to another robot
force release a transfer resource
mark package state manually
recover from blocked transfer-zone state
```

Implementation notes:

```text
add explicit recovery commands to the mission manager
validate robot availability, package state, and resource ownership
avoid letting the frontend mutate mission state directly
record every recovery action with actor, timestamp, old state, and new state
```

Possible endpoints:

```text
POST /missions/{mission_id}/actions/retry_task
POST /missions/{mission_id}/actions/reassign_task
POST /missions/{mission_id}/actions/force_release_resource
POST /missions/{mission_id}/actions/mark_item_state
```

Complexity: high.

### Level 6: Direct Robot or Nav2 Control

The operator bypasses RMF and commands the robot directly.

Examples:

```text
publish cmd_vel
send raw Nav2 goal
pause Nav2 controller
manual joystick control from the web UI
emergency stop
```

This should not be the first implementation target. Direct robot control can
conflict with RMF, the mission manager, package ownership, and transfer-zone
resource state.

If this is ever added, it should require an explicit manual-control workflow:

```text
enter_manual_control(robot):
  pause mission scheduling
  interrupt/cancel the robot's RMF task
  mark robot unavailable to RMF
  enable direct control

exit_manual_control(robot):
  stop direct commands
  verify robot pose/state
  recommission robot
  choose recovery action
```

Complexity: very high.

Recommended implementation order:

```text
1. mission pause/resume/abort
2. task cancel/interrupt/resume
3. robot decommission/recommission
4. direct RMF "send robot to waypoint"
5. mission recovery actions
6. direct Nav2/manual control only if required
```

---

## 7. Persistent Run Records, Rosbags, and AI-Ready Exports

The current RMF web API already has a database layer for operational entities
such as task states, task logs, alerts, and scheduled tasks. For a lab system,
that storage should become a broader experiment record.

The database should store searchable metadata and structured history. Large
artifacts should live on disk or object storage.

Suggested responsibilities:

```text
database:
  mission/run metadata
  task history
  alert history
  operator actions
  artifact metadata

filesystem or object storage:
  rosbag files
  compressed ROS logs
  exported JSON bundles
  screenshots or reports

API server:
  list/search run records
  start/stop recording requests
  expose artifact download endpoints
  build export bundles for later analysis
```

Avoid storing large rosbag binaries directly in the SQL database. Store file
path, size, checksum, topic list, time range, and related mission/run ID in the
database.

Possible backend shape:

```text
mission_run:
  id
  mission_id
  started_at
  ended_at
  status
  map_name
  robot_names
  software_commit
  notes

artifact:
  id
  run_id
  type: rosbag | ros_log | api_log | mission_export | screenshot
  path
  size_bytes
  sha256
  topics
  start_time
  end_time
  created_at
```

Possible API endpoints:

```text
GET  /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/artifacts
GET  /artifacts/{artifact_id}/download
POST /recordings/start
POST /recordings/stop
POST /runs/{run_id}/export
```

For AI-agent processing, prefer a self-contained export bundle rather than a
raw database dump:

```text
run_manifest.json
mission_state_timeline.json
task_states.json
alerts.json
operator_actions.json
rosbag/
logs/
```

A practical first step is to move the API server away from the default
in-memory SQLite configuration, confirm task states and logs survive a restart,
then add `mission_run` and `artifact` records before adding rosbag recording
controls.

---

## Practical Roadmap

Build in this order:

```text
1. Split ROS mission payloads into mission_state, mission_debug_state, and mission_events.
2. Shape mission_state to the compact dashboard/operator contract.
3. Expose mission lifecycle and state through the API server.
4. Add live mission updates to the dashboard.
5. Replace mock dashboard data with API-backed data.
6. Add mission pause/resume/abort.
7. Add task-level intervention controls.
8. Add robot availability controls.
9. Add run/artifact persistence.
10. Add rosbag/log export workflows.
11. Add higher-level recovery actions only after the basic intervention path is reliable.
```

This order keeps the UI useful early while avoiding direct robot override before
the mission state and recovery story are ready.
