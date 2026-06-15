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
7. Done: add API-server subscriptions and websocket rooms for state/events/debug.
8. Done: replace mock-only dashboard data with a live mission-state overlay.
9. Done: replace the Mission tab's synthetic map panel with a mission-flow panel.
10. Done: reorganize the Mission tab around mission overview, flow, steps, details, and activity.
11. Next: dry-test the ROS topic -> API server -> Socket.IO -> Mission tab path.
12. Next: add mission command endpoints for start/pause/resume/abort.
13. Later: consider namespacing topics only after the web/API bridge and execution bridge are validated.
```

The web/API bridge currently keeps the dashboard usable without lab data. The
Mission tab starts from mock scenario data, then overlays live `mission_state`
and `mission_events` when they arrive through the API server. Fields that belong
to RMF/fleet telemetry, such as battery level and exact map position, remain
mock/fallback values until the RMF streams are available.

### 3.2. Implemented Web/API Bridge

The first web-side integration work was implemented in the nested `web`
repository on branch `mission-topic-payload-split`.

Backend API server changes:

```text
web/packages/api-server/api_server/rmf_io/events.py
  added MissionEvents subjects for mission_state, mission_debug_state, mission_events

web/packages/api-server/api_server/gateway.py
  subscribes to ROS String JSON topics:
    mission_state
    mission_debug_state
    mission_events
  parses JSON and forwards the payloads into MissionEvents

web/packages/api-server/api_server/routes/missions.py
  added:
    GET /missions/current/state
    GET /missions/current/debug_state
    Socket.IO /missions/current/state
    Socket.IO /missions/current/debug_state
    Socket.IO /missions/current/events

web/packages/api-server/api_server/app.py
web/packages/api-server/api_server/routes/__init__.py
web/packages/api-server/api_server/rmf_io/__init__.py
  registered the mission routes and event dependencies
```

Frontend/API-client changes:

```text
web/packages/api-client/lib/index.ts
  added generic mission payload types
  added Socket.IO helpers:
    subscribeMissionState
    subscribeMissionDebugState
    subscribeMissionEvents

web/packages/rmf-dashboard-framework/src/services/rmf-api.ts
  exposed frontend observables:
    missionStateObs
    missionDebugStateObs
    missionEventsObs

web/packages/rmf-dashboard-framework/src/utils/test-utils.test.tsx
  updated mock RMF API service with mission observable subjects
```

Mission dashboard live overlay:

```text
web/packages/rmf-dashboard-framework/src/components/mission/live-dashboard-data.ts
  maps raw compact mission_state into the existing dashboard data shape
  keeps mock/fallback values for non-mission-owned telemetry such as battery and map position

web/packages/rmf-dashboard-framework/src/components/mission/use-dashboard-data.ts
  starts with demo scenario data
  overlays live mission_state when received
  appends mission_events into the event/activity stream
```

Verification performed at the time of implementation:

```text
python3 -m py_compile for changed API server files
pnpm --dir packages/api-client exec tsc --noEmit
eslint on changed frontend/API-client files
vite build for packages/rmf-dashboard-framework/examples/demo
```

The full framework TypeScript check still had pre-existing Storybook typing
issues unrelated to mission work.

### 3.3. Implemented Mission Dashboard Layout Update

The second web-side UI pass was implemented in the nested `web` repository on
branch `mission-flow-dashboard-ui`.

Changed mission UI files:

```text
web/packages/rmf-dashboard-framework/src/components/mission/mission-flow-view.tsx
  new mission-specific flow panel
  replaces the previous synthetic map in the Mission tab layout
  shows Source -> Transfer -> Destination mission semantics
  groups package chips by source, transfer, destination, and active legs
  highlights active source-to-transfer and transfer-to-destination work
  exposes an "Open RMF Map" action for spatial inspection

web/packages/rmf-dashboard-framework/src/components/mission/activity-panel.tsx
  new combined Activity panel
  puts mission events and alerts behind Events / Alerts tabs
  shows open-alert count and preserves alert select/acknowledge behavior

web/packages/rmf-dashboard-framework/src/components/mission/mission-dashboard.tsx
  reorganized the first viewport:
    left: Mission Overview and Robots
    center: Mission Flow and Mission Steps
    right: Detail Panel and Activity

web/packages/rmf-dashboard-framework/src/components/mission/fleet-panel.tsx
  replaced the wide fleet table with compact mission-relevant robot cards
  keeps robot selection, status, task, location, battery, and issue display

web/packages/rmf-dashboard-framework/src/components/mission/mission-timeline.tsx
  renamed visual intent from Mission Timeline to Mission Steps
  groups package-like tasks by package ID when task IDs/labels contain P1, P2, etc.
  caps panel height so details and activity remain visible

web/packages/rmf-dashboard-framework/src/components/mission/top-bar.tsx
  renamed Scenario to Demo Scenario to make mock-data usage explicit
```

Verification performed:

```text
eslint on changed mission UI files
pnpm --dir packages/rmf-dashboard-framework exec tsc --noEmit --skipLibCheck
vite build for packages/rmf-dashboard-framework/examples/demo
```

The Vite dev server hit the machine file watcher limit during verification, so
the built demo was served with `vite preview` instead.

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

The Mission tab should be the coordination surface for the operator. It should
not be treated as a smaller copy of the RMF Map tab. The central split is:

```text
Mission tab:
  operational intent, package flow, task ownership, blockers, next action

Map tab:
  physical location, building geometry, robot pose, traffic lanes, doors/lifts

Robots tab:
  fleet health, battery, mode, online/offline state, robot-specific diagnosis

Tasks tab:
  RMF task lifecycle, task details, cancellation/interruption controls
```

For the current two-robot handoff mission, the main Mission tab visual should
focus on the mission semantics:

```text
Source / pickup queue
  packages waiting at source
  active package being moved by tb3_1

Source-to-transfer leg
  upstream robot
  active source_to_transfer task
  blocked/waiting state if transfer is unavailable

Transfer zone
  resource status
  package buffer
  robot occupancy
  active lease/waiting reason when available

Transfer-to-destination leg
  downstream robot
  active transfer_to_destination task
  blocked/waiting state if package is unavailable

Destination / dropoff queue
  delivered packages
  remaining packages
```

This is why the first UI refinement replaced the synthetic Mission-tab map with
`MissionFlowView`. The old map-like panel was using mission dashboard positions
as fake percentages. It looked spatial, but it was not the authoritative
building map, robot pose, lane graph, or trajectory source. The Mission tab
should not imply spatial truth unless it is rendering from the same RMF map and
fleet streams as the real Map tab.

The Mission Flow panel is not meant to be the final form. It is the first
operator-facing representation of mission intent. As mission complexity grows,
it should become more state-based and less step-list-based.

Simple current form:

```text
Source -> Transfer -> Destination
tb3_1 handles source -> transfer
tb3_2 handles transfer -> destination
```

Better near-term form:

```text
Source
  waiting: P2, P3
  active pickup: P1

tb3_1 source -> transfer
  carrying or moving P1
  current status / blocker

Transfer
  available or occupied
  buffered package: P1 or none
  waiting robot/package

tb3_2 transfer -> destination
  ready, moving, waiting, or blocked

Destination
  delivered: 0 / 3
  next expected package
```

Larger mission form:

```text
Source A        Source B
waiting: 4      waiting: 2
active: P7      active: P11

Upstream robots:
  3 active
  1 blocked

Transfer / buffer resources:
  queue: P2, P5, P8
  blocked: P5 waiting 4m

Downstream robots:
  2 active
  1 idle

Destinations:
  delivered: 13 / 20
  late: 2
```

For non-linear missions, the flow can become a small mission graph:

```text
Pickup A -> Inspect -> Transfer -> Dropoff A
Pickup B ----------^
Pickup C -> Buffer -> Transfer -> Dropoff B
```

The important rule is to collapse normal things and expand abnormal things.
This is partly a UI behavior rule and partly an information-priority rule.

Normal state should be summarized:

```text
8 robots healthy
12 packages on schedule
3 resources available
```

Abnormal state should be expanded automatically:

```text
tb3_4 blocked near transfer
P6 waiting 6m at transfer
Dropoff B unavailable
Operator confirmation required for P9 pickup
```

This can use expandable/collapsible UI components, but it should not depend
only on manual expanders. The dashboard should visually prioritize active,
waiting, blocked, failed, delayed, and operator-required states before normal
background work.

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

Additional recommended Mission tab panels:

```text
Attention strip:
  hidden when normal
  shows top mission blockers, delayed packages, failed tasks, and operator-required actions

Active work:
  active package/task
  responsible robot
  current leg
  next expected state transition

Mission resources:
  only mission-relevant robots and resources
  transfer zone, staging/wait areas, package buffers

Details/activity:
  selected robot/task/zone/alert detail
  mission-filtered events and alerts
```

The mission UI should make these questions answerable without scanning the full
fleet:

```text
What is moving?
What is waiting?
What is blocked?
Who owns the next action?
Where should the operator click to inspect or intervene?
```

The Mission tab should link into the existing Open-RMF tabs instead of copying
their full function:

```text
Click active robot:
  open Robots tab or Map tab focused on that robot

Click transfer zone:
  open Map tab focused on the corresponding waypoint/place when available

Click mission task:
  open Tasks tab filtered or selected to the RMF/custom task

Click alert:
  keep mission context in the Mission tab and expose related robot/task/map links
```

This requires later shared selection/focus plumbing between tabs. The current
`Open RMF Map` button is a first step; robot/zone/task-specific focus should be
added after the mission state identifies RMF fleet names, robot names, RMF task
IDs, and map waypoint/place IDs reliably.

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
6. Dry-test the integrated observation path with manual ROS topic publications.
7. Add mission pause/resume/abort API commands.
8. Add task-level intervention controls.
9. Add robot availability controls.
10. Add run/artifact persistence.
11. Add rosbag/log export workflows.
12. Add higher-level recovery actions only after the basic intervention path is reliable.
```

This order keeps the UI useful early while avoiding direct robot override before
the mission state and recovery story are ready.
