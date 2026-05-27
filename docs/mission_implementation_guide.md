# Multi-Robot Delivery Mission Layer

## Implementation Guide v1

This guide describes the v1 mission layer for a fixed two-robot delivery mission:

```text
source A -> transfer B -> destination C

Robot 1: source A -> transfer B
Robot 2: transfer B -> destination C
```

Zone X is a staging/waiting zone near transfer B. It is used only when a robot cannot enter B yet; it is not part of the normal upstream route when B is available.

The mission layer runs above Open-RMF. RMF handles robot execution, traffic coordination, and task state. The mission layer handles package state, transfer-zone policy, dispatch timing, and mission state exposed to the UI.

For v1, mission "delivery" is implemented using RMF patrol/loop-style waypoint tasks. It is not a native RMF delivery task.

---

## 1. Runtime Shape

```text
rmf-web Mission UI
        ↓
Mission API
        ↓
Mission Manager
        ↓
RMF Bridge
        ↓
Open-RMF / free_fleet
        ↓
Robots
```

Reverse flow:

```text
RMF task/fleet updates
        ↓
RMF Bridge
        ↓
mission events
        ↓
Mission Manager
        ↓
mission state
        ↓
Mission API / UI
```

---

## 2. Backend Modules

Current package layout:

```text
rmf_ws/src/mrd_mission_manager/
├── mrd_mission_manager/
│   ├── __init__.py
│   ├── actions.py
│   ├── events.py
│   ├── mission_manager.py
│   ├── mission_manager_node.py
│   ├── mission_state.py
│   ├── rmf_bridge.py
│   ├── rule_evaluator.py
│   └── transfer_controller.py
├── test/
│   ├── test_mission_manager.py
│   └── test_rmf_bridge.py
├── package.xml
├── setup.cfg
└── setup.py
```

Responsibilities:

* `mission_state.py`: mission/package/robot/transfer data models
* `events.py`: mission-level event definitions
* `actions.py`: commands emitted by the rule evaluator
* `transfer_controller.py`: Zone B entry and buffer rules
* `rule_evaluator.py`: dispatch and completion rules
* `mission_manager.py`: receives events, updates state, emits actions
* `rmf_bridge.py`: RMF task request building, response handling, and completion-to-event translation
* `mission_manager_node.py`: ROS 2 runtime wrapper for RMF task API topics

---

## 3. State Models

### Mission State

```python
class MissionStatus(Enum):
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
```

```python
class MissionState:
    mission_id: str
    status: MissionStatus
    total_packages: int
    delivered_count: int
    upstream_robot_id: str
    downstream_robot_id: str
    packages: dict[str, PackageRecord]
    transfer: TransferZoneState
    robots: dict[str, RobotMissionState]
```

### Package State

```python
class PackageStatus(Enum):
    AT_SOURCE = "AT_SOURCE"
    INBOUND_TO_TRANSFER = "INBOUND_TO_TRANSFER"
    AT_TRANSFER = "AT_TRANSFER"
    INBOUND_TO_DESTINATION = "INBOUND_TO_DESTINATION"
    DELIVERED = "DELIVERED"
```

```python
class PackageRecord:
    package_id: str
    status: PackageStatus
    upstream_task_id: str | None
    downstream_task_id: str | None
```

Task IDs are tracked so repeated RMF updates do not cause duplicate dispatches.

The mission specification allows up to three active packages at once:

```text
1 package assigned to Robot 1 on the upstream leg
1 package buffered at transfer B
1 package assigned to Robot 2 on the downstream leg
```

This is still bounded by the transfer rules: Robot 1 must not dispatch another drop-off into B while the transfer package buffer is occupied.

### Transfer Zone State

```python
class TransferZoneState:
    robot_occupancy: str | None
    package_buffer: str | None
    waiting_robot: str | None
    waiting_package: str | None
```

Zone B rules:

* only one robot may occupy Zone B
* only one package may be buffered at Zone B
* Robot 1 may enter B only if robot occupancy is free and the package buffer is empty
* Robot 2 may enter B only if robot occupancy is free and a package is buffered
* staging zone X is used for waiting near B when transfer entry is blocked

A robot may wait at X, but cannot enter B unless its entry condition is satisfied.

The staging zone can be shared or split by role:

```text
shared staging:
  one Zone X used by both robots

role-specific staging:
  upstream staging near B for Robot 1
  downstream staging near B for Robot 2
```

The mission logic should treat staging as a waiting position for transfer entry, not as a package buffer.

### Robot Mission State

```python
class RobotStatus(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    LOADING = "LOADING"
    UNLOADING = "UNLOADING"
    WAITING_AT_STAGING = "WAITING_AT_STAGING"
    RETURNING = "RETURNING"
```

The current code implements the movement-oriented subset of these statuses. `LOADING` and `UNLOADING` are part of the mission specification and should be modeled as 5 second mission-layer delays.

`RETURNING` means the robot is repositioning after a completed leg. It does not always mean returning home. During normal mission flow, a robot may return/reposition to staging if it cannot immediately enter transfer B. Robots return home/charging on mission completion or explicit operator command.

```python
class RobotMissionState:
    robot_id: str
    status: RobotStatus
    active_task_id: str | None
    active_package_id: str | None
```

---

## 4. Mission Events

The RMF bridge may observe lower-level RMF facts such as task state, robot state, task phase, or waypoint arrival. The mission manager should receive mission-level events only.

```python
class MissionStarted:
    mission_id: str

class RobotBecameIdle:
    mission_id: str
    robot_id: str

class RobotArrivedAtStaging:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str

class DownstreamRobotArrivedAtStaging:
    mission_id: str
    robot_id: str
    task_id: str

class UpstreamLegCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str

class DownstreamPickupCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str

class DownstreamLegCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    task_id: str

class HandlingTimerCompleted:
    mission_id: str
    robot_id: str
    package_id: str
    handling_type: str

class OperatorPaused:
    mission_id: str

class OperatorResumed:
    mission_id: str

class OperatorAborted:
    mission_id: str
```

Event source mapping:

| Event | Source | State effect |
| --- | --- | --- |
| `MissionStarted` | Mission API | mission becomes `RUNNING` |
| `RobotBecameIdle` | RMF task/fleet state | robot becomes available for mission work |
| `RobotArrivedAtStaging` | RMF task completion | Robot 1 waits at staging X with a package |
| `DownstreamRobotArrivedAtStaging` | RMF task completion | Robot 2 waits at staging X without a package |
| `UpstreamLegCompleted` | RMF task completion | Robot 1 arrived at B and starts transfer unloading |
| `DownstreamPickupCompleted` | RMF task completion | Robot 2 arrived at B and starts transfer loading |
| `DownstreamLegCompleted` | RMF task completion | Robot 2 arrived at C and starts destination unloading |
| `HandlingTimerCompleted` | ROS timer | loading/unloading completes and package/transfer state is updated |
| `OperatorPaused` | Mission API | stop future dispatch |
| `OperatorResumed` | Mission API | resume rule evaluation |
| `OperatorAborted` | Mission API | stop mission permanently |

Event handler pattern:

```python
def handle_event(event):
    update_state(event)
    actions = evaluate_rules(state)
    emit_actions(actions)
```

All event handling should be idempotent. Before emitting a dispatch action, check task IDs and robot/package active state.

---

## 5. Mission Actions

Events are facts that have already happened. Actions are commands emitted by the rule evaluator.

```python
class DispatchTask:
    robot_id: str
    package_id: str
    segment: TaskSegment

class PositionRobot:
    robot_id: str
    segment: TaskSegment

class StartHandlingTimer:
    robot_id: str
    package_id: str
    handling_type: str
    seconds: float = 5.0

class SendRobotHome:
    robot_id: str

class CompleteMission:
    pass
```

The RMF bridge consumes movement actions and turns them into RMF patrol/loop-style waypoint tasks. The ROS node consumes `StartHandlingTimer` actions and creates mission-layer timers. The mission manager should not publish RMF tasks directly from `update_state`; dispatch should happen only through emitted actions.

When a dispatch action succeeds, record the returned RMF task ID immediately:

```text
package.upstream_task_id or package.downstream_task_id = task_id
robot.active_task_id = task_id
robot.active_package_id = package_id
```

This prevents the next rule evaluation from dispatching the same package again.

Current implementation uses `record_dispatch(action, task_id)` on `MissionManager` for this step.

Package-free positioning actions use `record_position_dispatch(action, task_id)` to mark the robot as repositioning without assigning a package.

---

## 6. Transfer Controller

Core functions:

```python
def can_robot_enter(robot_id: str, package_id: str | None) -> bool: ...
def occupy_transfer(robot_id: str) -> None: ...
def release_transfer(robot_id: str) -> None: ...
def buffer_package(package_id: str) -> None: ...
def release_package(package_id: str) -> None: ...
def set_waiting_robot(robot_id: str, package_id: str) -> None: ...
def clear_waiting_robot(robot_id: str) -> None: ...
```

Entry rules:

```text
Robot 1 entry:
  transfer.robot_occupancy is None
  AND transfer.package_buffer is None

Robot 2 entry:
  transfer.robot_occupancy is None
  AND transfer.package_buffer is not None
```

Release rules:

```text
Robot occupancy is released when a robot exits B.
Package buffer is filled when Robot 1 completes drop-off at B.
Package buffer is released when Robot 2 completes pickup from B.
```

For v1, pickup/drop-off may be logical state transitions tied to RMF task completion, not physical sensor confirmations.

---

## 7. Rule Evaluator

### Start Upstream Package

```text
IF mission is RUNNING
AND Robot 1 is IDLE
AND there is a package AT_SOURCE
AND selected package has no upstream_task_id
AND transfer.package_buffer is None
THEN:
  IF Robot 1 can enter transfer B
    dispatch Robot 1 from source/load waypoint directly to transfer B
  ELSE
    dispatch Robot 1 from source/load waypoint to staging X
```

This matches the mission specification: Robot 1 waits at staging X only when transfer entry is blocked. Staging X should not be treated as a mandatory checkpoint.

### Grant Transfer Entry

```text
IF mission is RUNNING
AND transfer.waiting_robot is not None
AND can_robot_enter(waiting_robot, waiting_package)
THEN dispatch waiting robot into transfer B
```

### Start Downstream Package

```text
IF mission is RUNNING
AND Robot 2 is IDLE
AND transfer.package_buffer contains package_id
AND selected package has no downstream_task_id
AND Robot 2 can enter transfer B
THEN dispatch Robot 2 from idle/staging/current position to transfer B
```

The current implementation can also proactively place Robot 2 at staging X while it is waiting for transfer pickup work.

Downstream staging rule:

```text
IF mission is RUNNING
AND Robot 2 is IDLE
AND there is no package available for pickup at B
OR transfer B is occupied by another robot
THEN dispatch Robot 2 to staging X
```

Then:

```text
IF Robot 2 is waiting at staging X
AND transfer.package_buffer contains package_id
AND transfer.robot_occupancy is None
THEN dispatch Robot 2 from staging X into transfer B
```

The current implementation models this with package-free robot positioning actions. Upstream staging still tracks a waiting package; downstream staging only tracks Robot 2's waiting position.

### Reposition After Each Leg

During normal mission flow, "return" means reposition for the next transfer opportunity:

```text
Robot 1 after unloading at B:
  IF another source package is available
  AND Robot 1 can enter B for the next drop-off when needed
    continue with the next upstream assignment
  ELSE
    move/wait at upstream staging

Robot 2 after unloading at C:
  IF a package is buffered at B
  AND Robot 2 can enter B
    dispatch Robot 2 directly to B for pickup
  ELSE
    move/wait at downstream staging
```

Home/charging return is mission-completion behavior, not the normal loop between packages.

### Continue Downstream Delivery

```text
IF mission is RUNNING
AND Robot 2 is IDLE
AND Robot 2 is carrying a package picked from transfer
AND package is INBOUND_TO_DESTINATION
AND selected package has no downstream_task_id
THEN dispatch Robot 2 from transfer B to destination C
```

### Complete Mission

```text
IF delivered_count == total_packages
THEN mission.status = COMPLETED
AND send robots home
```

### Pause / Resume

V1 uses soft pause:

```text
PAUSED:
  do not dispatch new RMF tasks
  continue consuming RMF updates
  allow active RMF tasks to finish

RESUMED:
  set mission back to RUNNING
  evaluate rules again
```

Hard pause, task interrupt, task cancel, and task resume are later extensions.

---

## 8. Simulated Package Handling

The current implementation models package handling as mission-layer timers, not RMF behavior. RMF moves robots between waypoints. The mission layer decides when package state changes after loading or unloading completes.

Use a 5 second delay for each handling operation:

* source loading
* transfer drop-off
* transfer pickup
* destination unloading

Timer-based handling can be modeled as actions and events:

```python
class StartHandlingTimer:
    robot_id: str
    package_id: str
    handling_type: str
    seconds: float = 5.0

class HandlingTimerCompleted:
    robot_id: str
    package_id: str
    handling_type: str
```

Recommended ownership:

```text
RMF bridge:
  translate RMF task completion into mission events

Mission manager:
  update mission/package/robot/transfer state
  emit StartHandlingTimer when loading/unloading should begin
  consume HandlingTimerCompleted events

Mission manager ROS node:
  create and fire ROS timers for StartHandlingTimer actions

Rule evaluator:
  dispatch the next movement only after handling completion updates state
```

Example transfer drop-off flow:

```text
Robot 1 completes source_to_transfer or staging_to_transfer
  -> robot status becomes UNLOADING
  -> start transfer drop-off timer
  -> timer completes
  -> package becomes AT_TRANSFER
  -> transfer.package_buffer = package_id
  -> Robot 1 leaves/releases B
```

Example transfer pickup flow:

```text
Robot 2 completes home_to_transfer or staging_to_transfer
  -> robot status becomes LOADING
  -> start transfer pickup timer
  -> timer completes
  -> transfer.package_buffer is released
  -> package becomes INBOUND_TO_DESTINATION
  -> dispatch Robot 2 to destination C
```

This should be added before the demo if the UI needs to visibly show package handling time.

---

## 9. RMF Bridge

The current bridge implementation is `mrd_mission_manager/rmf_bridge.py`. It is ROS-free and is driven by the ROS node through injected publish callbacks and RMF task API messages.

### Inbound: RMF To Mission

The ROS node subscribes to RMF task updates and passes them to the bridge, which maps completed mission task IDs to mission events.

Examples:

```text
RMF task completed for segment=source_to_transfer
  -> UpstreamLegCompleted

RMF task completed for segment=source_to_staging
  -> RobotArrivedAtStaging

RMF task completed for segment=staging_to_transfer, leg=upstream
  -> UpstreamLegCompleted

RMF task completed for segment=home_to_transfer, leg=downstream
  -> DownstreamPickupCompleted

RMF task completed for segment=transfer_to_destination, leg=downstream
  -> DownstreamLegCompleted

RMF robot/task state indicates no active mission task
  -> RobotBecameIdle
```

The bridge keeps a mapping from RMF task ID to mission context:

```python
task_context_by_id = {
    "task_123": TaskContext(
        mission_id="m1",
        package_id="P3",
        robot_id="tb3_1",
        segment=TaskSegment.STAGING_TO_TRANSFER,
    )
}
```

### Outbound: Mission To RMF

Implemented dispatch entrypoint:

```python
def submit_action(action: DispatchTask | SendRobotHome) -> str | None: ...
```

`submit_action(...)` builds a robot-specific patrol request and publishes it through the injected callback. The bridge records the RMF task ID later when `task_api_responses` returns a successful response.

Suggested v1 task segments:

```text
Robot 1:
  source/load waypoint -> transfer B
  source/load waypoint -> staging X, only if transfer entry is blocked
  staging X -> transfer B, once transfer entry is available
  transfer B -> upstream staging, if it cannot immediately continue

Robot 2:
  idle/staging/current position -> transfer B
  transfer B -> destination C
  destination C -> transfer B, if a package is waiting and B is available
  destination C -> downstream staging, if B is not ready
  staging X -> transfer B, once pickup is available
  current position -> home/charging, on mission completion
```

The mission manager decides when to submit each segment.

The current ROS node submits these actions on `task_api_requests` as `rmf_task_msgs/msg/ApiRequest` messages.

---

## 10. Mission API

Endpoints:

```text
POST /missions
POST /missions/{mission_id}/start
POST /missions/{mission_id}/pause
POST /missions/{mission_id}/resume
POST /missions/{mission_id}/abort
GET  /missions/{mission_id}
```

Response shape:

```json
{
  "mission_id": "m1",
  "status": "RUNNING",
  "total_packages": 30,
  "delivered_count": 12,
  "remaining_count": 18,
  "transfer": {
    "robot_occupancy": "tb3_1",
    "package_buffer": "P5",
    "waiting_robot": null,
    "waiting_package": null
  },
  "robots": {
    "tb3_1": {
      "status": "MOVING",
      "active_package_id": "P6",
      "active_task_id": "task_123"
    },
    "tb3_2": {
      "status": "IDLE",
      "active_package_id": null,
      "active_task_id": null
    }
  }
}
```

---

## 11. Mission UI

The rmf-web mission tab should consume the Mission API and show:

* mission status
* delivered / total package count
* package statuses
* transfer robot occupancy
* transfer package buffer
* waiting robot at staging
* Robot 1 and Robot 2 mission status and logical location
* active package/task IDs
* active handling timers
* recent mission events
* recent emitted actions and RMF task IDs for debugging

Controls:

* start
* pause
* resume
* abort

Recommended web/API build order:

1. Add a mission-state serializer shared by tests and the future API.
2. Add Mission API endpoints for create/start/pause/resume/abort/get-state.
3. Decide ownership: either the API backend talks to the ROS mission node, or the mission manager runs inside the backend. Prefer one live mission authority.
4. Add live updates with WebSockets, Server-Sent Events, or short polling.
5. Add an rmf-web mission tab focused on mission status, robot/package state, transfer state, controls, and a recent event/action log.
6. Add debug visibility before UI polish: last event, last action, active RMF task IDs, active handling timers, transfer occupancy, and package buffer.

---

## 12. Implementation Order

1. Implement state models and event classes. Done.
2. Implement `handle_event(event)` with pure state transitions. Done.
3. Implement transfer controller functions. Done.
4. Implement rule evaluator and action emission. Done for the current fixed two-robot mission.
5. Add RMF bridge task dispatch and task-context mapping. Done.
6. Translate RMF task completions into mission events. Done.
7. Add ROS 2 node wrapper for RMF task API topics. Done.
8. Validate the node against a live RMF deployment. Next.
9. Add Mission API endpoints. Pending.
10. Add rmf-web mission tab. Pending.

---

## 13. Implemented So Far

The current version in `rmf_ws/src/mrd_mission_manager` includes the mission core plus the first RMF bridge/node layer.

Implemented:

* `MissionManager.create(mission_id, total_packages)`
* `MissionManager.handle_event(event)`
* `MissionManager.record_dispatch(action, task_id)`
* `MissionManager.record_position_dispatch(action, task_id)`
* fixed default robot roles using `tb3_1` as upstream and `tb3_2` as downstream, with constructor/parameter overrides
* mission/package/robot/transfer state models
* transfer-zone entry, occupancy, buffer, and staging state helpers
* event handling for start, pause, resume, abort, upstream/downstream staging arrival, upstream completion, downstream pickup, downstream delivery, handling timer completion, and robot idle
* rule evaluation for source loading, direct source-to-transfer, conditional staging, transfer entry, downstream pickup, downstream destination dispatch, downstream staging/repositioning, and mission completion
* 5 second mission-layer loading/unloading timers through `StartHandlingTimer` and `HandlingTimerCompleted`
* Robot 2 proactive staging and direct destination-to-transfer return when pickup is ready
* RMF `robot_task_request` payload construction for patrol-style waypoint tasks
* RMF API response handling and task-context mapping
* RMF task completion translation back into mission events
* ROS 2 node wrapper for `task_api_requests`, `task_api_responses`, and `task_summaries`
* unittest coverage for mission core and RMF bridge behavior

Specification alignment still pending:

* live validation that patrol-style RMF requests produce the expected physical load/unload timing behavior
* richer handling of rejected RMF tasks, blocked robots, or unavailable robots

Current verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager python3 -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

Current limitation:

* node has not yet been validated against a live RMF deployment
* no launch/config file for the mission manager node yet
* no rejected-task retry or operator-visible failure state yet
* no Mission API endpoints yet
* no rmf-web mission tab yet
