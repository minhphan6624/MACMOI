# Multi-Robot Delivery Mission Layer

## Implementation Guide v1

This guide describes the v1 mission layer for a fixed two-robot delivery mission:

```text
source A -> transfer B -> destination C

Robot 1: source A -> transfer B
Robot 2: transfer B -> destination C
```

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
│   ├── mission_state.py
│   ├── rule_evaluator.py
│   └── transfer_controller.py
├── test/
│   └── test_mission_manager.py
├── package.xml
├── setup.cfg
└── setup.py
```

Planned package layout after RMF integration:

```text
mrd_mission_manager/
├── mission_state.py
├── events.py
├── actions.py
├── transfer_controller.py
├── rule_evaluator.py
├── mission_manager.py
├── rmf_bridge.py
└── mission_manager_node.py
```

Responsibilities:

* `mission_state.py`: mission/package/robot/transfer data models
* `events.py`: mission-level event definitions
* `actions.py`: commands emitted by the rule evaluator
* `transfer_controller.py`: Zone B entry and buffer rules
* `rule_evaluator.py`: dispatch and completion rules
* `mission_manager.py`: receives events, updates state, emits actions
* `rmf_bridge.py`: RMF task submission and RMF update translation, not implemented yet
* `mission_manager_node.py`: ROS 2 runtime wrapper, not implemented yet

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
* staging zone X is used for waiting near B

Staging X does not weaken the package-buffer rule. Robot 1 may wait at X, but cannot enter B unless the buffer can accept its package.

### Robot Mission State

```python
class RobotStatus(Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    WAITING_AT_STAGING = "WAITING_AT_STAGING"
    RETURNING = "RETURNING"
```

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
    pass

class RobotBecameIdle:
    robot_id: str

class RobotArrivedAtStaging:
    robot_id: str
    package_id: str | None
    task_id: str

class UpstreamLegCompleted:
    robot_id: str
    package_id: str
    task_id: str

class DownstreamPickupCompleted:
    robot_id: str
    package_id: str
    task_id: str

class DownstreamLegCompleted:
    robot_id: str
    package_id: str
    task_id: str

class OperatorPaused:
    pass

class OperatorResumed:
    pass

class OperatorAborted:
    pass
```

Event source mapping:

| Event | Source | State effect |
| --- | --- | --- |
| `MissionStarted` | Mission API | mission becomes `RUNNING` |
| `RobotBecameIdle` | RMF task/fleet state | robot becomes available for mission work |
| `RobotArrivedAtStaging` | RMF task completion | robot waits at staging X |
| `UpstreamLegCompleted` | RMF task completion | package becomes `AT_TRANSFER`, buffer is occupied, Robot 1 leaves B |
| `DownstreamPickupCompleted` | RMF task completion | package becomes `INBOUND_TO_DESTINATION`, buffer is released, Robot 2 leaves B |
| `DownstreamLegCompleted` | RMF task completion | package becomes `DELIVERED`, delivered count increments, Robot 2 becomes available |
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

class SendRobotHome:
    robot_id: str

class CompleteMission:
    pass
```

The RMF bridge consumes actions and turns them into RMF patrol/loop-style waypoint tasks. The mission manager should not publish RMF tasks directly from `update_state`; dispatch should happen only through emitted actions.

When a dispatch action succeeds, record the returned RMF task ID immediately:

```text
package.upstream_task_id or package.downstream_task_id = task_id
robot.active_task_id = task_id
robot.active_package_id = package_id
```

This prevents the next rule evaluation from dispatching the same package again.

Current implementation uses `record_dispatch(action, task_id)` on `MissionManager` for this step.

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
THEN dispatch Robot 1 from source/load waypoint to staging X
```

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
THEN dispatch Robot 2 from home/idle to transfer B
```

Current v1 implementation only starts Robot 2 when a package is already buffered and transfer B is enterable. It does not yet proactively send Robot 2 to staging X while Robot 1 is still occupying B.

Future downstream staging rule:

```text
IF mission is RUNNING
AND Robot 2 is IDLE
AND upstream work is likely to produce a transfer package soon
AND transfer B is occupied by Robot 1 or not yet ready for Robot 2
THEN dispatch Robot 2 to staging X
```

Then:

```text
IF Robot 2 is waiting at staging X
AND transfer.package_buffer contains package_id
AND transfer.robot_occupancy is None
THEN dispatch Robot 2 from staging X into transfer B
```

This requires either a downstream-specific staging state or a more general waiting-robot model, because Robot 2 may wait at staging without carrying a package.

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

The current implementation treats loading and unloading as immediate logical transitions tied to RMF task completion.

Not implemented yet:

* simulated source loading delay
* simulated transfer drop-off delay
* simulated transfer pickup delay
* simulated destination unloading delay

Future timer-based handling can be modeled as actions and events:

```python
class StartHandlingTimer:
    robot_id: str
    package_id: str
    handling_type: str
    seconds: float

class HandlingTimerCompleted:
    robot_id: str
    package_id: str
    handling_type: str
```

Example transfer drop-off flow:

```text
Robot 1 completes staging_to_transfer
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

### Inbound: RMF To Mission

The bridge subscribes to RMF/fleet/task updates and maps them to mission events.

Examples:

```text
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

Keep a mapping from RMF task ID to mission context:

```python
task_context_by_id = {
    "task_123": {
        "mission_id": "m1",
        "package_id": "P3",
        "robot_id": "tb3_1",
        "leg": "upstream",
        "segment": "staging_to_transfer",
    }
}
```

### Outbound: Mission To RMF

Dispatch functions:

```python
def dispatch_source_to_staging(robot_id: str, package_id: str) -> str: ...
def dispatch_into_transfer(robot_id: str, package_id: str) -> str: ...
def dispatch_to_destination(robot_id: str, package_id: str) -> str: ...
def send_robot_home(robot_id: str) -> str: ...
```

Each function submits a robot-specific patrol/loop-style waypoint task and returns the RMF task ID.

Suggested v1 task segments:

```text
Robot 1:
  source/load waypoint -> staging X
  staging X -> transfer B
  transfer B -> home/idle

Robot 2:
  home/idle -> transfer B
  transfer B -> destination C
  destination C -> home/idle
```

The mission manager decides when to submit each segment.

The current implementation stops at emitting these dispatch actions. It does not yet submit RMF tasks.

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
* transfer robot occupancy
* transfer package buffer
* waiting robot at staging
* Robot 1 and Robot 2 mission status
* recent mission events

Controls:

* start
* pause
* resume
* abort

---

## 12. Implementation Order

1. Implement state models and event classes. Done.
2. Implement `handle_event(event)` with pure state transitions. Done.
3. Implement transfer controller functions. Done.
4. Implement rule evaluator and action emission. Done.
5. Add RMF bridge task dispatch and task-context mapping. Next.
6. Translate RMF task completions into mission events. Pending.
7. Add Mission API endpoints. Pending.
8. Add rmf-web mission tab. Pending.

---

## 13. Implemented So Far

The initial version is a pure Python mission core in `rmf_ws/src/mrd_mission_manager`.

Implemented:

* `MissionManager.create(mission_id, total_packages)`
* `MissionManager.handle_event(event)`
* `MissionManager.record_dispatch(action, task_id)`
* fixed robot roles using `tb3_1` as upstream and `tb3_2` as downstream
* mission/package/robot/transfer state models
* transfer-zone entry, occupancy, buffer, and staging state helpers
* event handling for start, pause, resume, abort, staging arrival, upstream completion, downstream pickup, downstream delivery, and robot idle
* rule evaluation for upstream dispatch, transfer entry, downstream pickup, downstream destination dispatch, and mission completion
* unittest smoke coverage for one-package completion and pause blocking new dispatch

Current verification command:

```bash
PYTHONPATH=rmf_ws/src/mrd_mission_manager /home/minhqphan/miniconda3/envs/fall-tsad/bin/python -m unittest discover -s rmf_ws/src/mrd_mission_manager/test
```

Current limitation:

* no ROS 2 node yet
* no RMF task submission yet
* no task-context mapping from RMF task ID to mission package/segment yet
* no Robot 2 proactive staging behavior while Robot 1 occupies transfer B
* no simulated package loading/unloading timers
* no Mission API endpoints yet
* no rmf-web mission tab yet
