# Mission Layer Current Architecture

This document is the current source-of-truth for the `mrd_mission_manager`
architecture. The mission layer now runs on generalized transport tasks,
runtime world state, resource management, execution commands, and an RMF
execution adapter.

The old mission-controller path based on a mission-specific FSM, rule evaluator,
transfer controller, task segments, and bridge-level mission semantics has been
removed from the active runtime.

---

## 1. Runtime Shape

The active runtime path is:

```text
MissionManagerNode
  -> MissionOrchestrator
  -> TransportTaskScheduler
  -> TransportTaskRunner
  -> ExecutionManager
  -> RmfExecutionAdapter / handling timer
  -> command completion
  -> MissionOrchestrator
```

The main separation is:

```text
MissionManagerNode:
  ROS I/O and timers

MissionOrchestrator:
  mission lifecycle and task coordination

TransportTaskScheduler:
  chooses ready transport tasks

TransportTaskRunner:
  advances one transport task workflow

RuntimeWorld:
  robot, item, and resource truth

WorldResourceManager:
  resource acquisition, occupancy, and buffer operations

ExecutionManager:
  execution command lifecycle

RmfExecutionAdapter:
  RMF task API adapter for robot movement commands
```

The current mission behavior is still the two-robot package handoff:

```text
source -> transfer -> destination

tb3_1 transports item from source to transfer
tb3_2 transports item from transfer to destination
```

That behavior is represented as task instances instead of mission-specific
segments:

```text
transportItem(P1, source, transfer, tb3_1)
transportItem(P1, transfer, destination, tb3_2)
```

### Source Map

The active mission runtime is implemented in:

```text
mission_manager_node.py       ROS node, topics, timers, RMF subscriptions
orchestrator.py               mission lifecycle and task coordination
mission_tasks.py              mission/task status and transport task model
scheduler.py                  deterministic ready-task selection
task_runner.py                transport task workflow runner
world.py                      robot/item world state
world_resource_manager.py     resource acquisition and buffer rules
resources.py                  generic resource state model
execution.py                  execution command lifecycle
rmf_execution_adapter.py      RMF task API adapter for movement commands
mission_serializer.py         mission_state JSON serialization
```

---

## 2. MissionManagerNode

`mission_manager_node.py` is the ROS runtime shell.

It owns:

* ROS publishers/subscribers
* mission command handling
* RMF task API request publication
* RMF task response and task summary subscriptions
* fleet-state fallback completion detection
* simulated handling timers
* mission-state publication
* recent command/debug history

It does not own mission policy. It delegates mission behavior to the
`MissionOrchestrator`.

### Inputs

Mission commands arrive on the configured mission command topic as JSON:

```json
{"command": "start", "mission_id": "m1"}
```

RMF updates arrive through:

```text
task_api_responses
task_summaries
fleet_states
```

### Outputs

The node publishes:

```text
task_api_requests
mission_state
```

### Command Dispatch

The node dispatches `ExecutionCommand`s:

```text
MOVE_ROBOT
  -> RmfExecutionAdapter.submit_command(...)

HANDLE_ITEM
  -> ROS timer
```

When a handling timer fires, the node completes the command:

```text
orchestrator.complete_command(command_id)
```

---

## 3. MissionOrchestrator

`orchestrator.py` owns the mission runtime.

It contains:

```text
MissionRuntime
MissionOrchestrator
```

`MissionRuntime` holds:

* `mission_id`
* mission status
* transport task instances
* `RuntimeWorld`

`MissionOrchestrator` owns:

* `TransportTaskScheduler`
* `TransportTaskRunner`
* `ExecutionManager`

The orchestrator is responsible for:

* creating the default mission runtime
* starting the mission
* ticking the scheduler
* starting ready tasks
* receiving completed command IDs
* advancing task workflows
* marking the mission completed when all tasks succeed

It does not publish ROS messages or RMF requests directly.

### Default Mission Creation

`MissionOrchestrator.create_default(...)` creates:

* one `WorldItemState` per package
* two `TransportItemTask` instances per package
* default robot states for upstream/downstream robots
* one transfer resource with one robot slot and one package slot

For package `P1`, the default tasks are:

```text
P1:source_to_transfer
  item_id = P1
  pickup = source
  dropoff = transfer
  robot_id = tb3_1

P1:transfer_to_destination
  item_id = P1
  pickup = transfer
  dropoff = destination
  robot_id = tb3_2
```

---

## 4. Mission Tasks

`mission_tasks.py` defines the task model.

Main types:

```text
MissionStatus
MissionTaskType
MissionTaskStatus
TransportTaskPhase
TransportItemTask
```

The currently implemented mission task type is:

```text
transport_item
```

`TransportItemTask` describes one movement of one item:

```text
task_id
item_id
pickup
dropoff
robot_id
status
required_resources
phase
active_command_id
waiting_resource_id
waiting_purpose
```

Task phases are intentionally explicit:

```text
NOT_STARTED
ACQUIRE_PICKUP
MOVE_TO_PICKUP
LOAD_ITEM
ACQUIRE_DROPOFF
MOVE_TO_STAGING
WAIT_FOR_RESOURCE
MOVE_TO_DROPOFF
UNLOAD_ITEM
DONE
```

These phases are the current lightweight workflow representation. Later, they
can be replaced by, or wrapped with, a behavior tree executor.

---

## 5. Scheduler

`scheduler.py` defines `TransportTaskScheduler`.

The scheduler chooses the next ready `TransportItemTask`.

Current readiness checks:

```text
task status is PENDING
task has an assigned robot
assigned robot is available
item is at the task pickup location
```

For the default mission, this means:

```text
1. P1:source_to_transfer can start while P1 is at source.
2. P1:transfer_to_destination can start after P1 reaches transfer.
```

The current scheduler is deterministic and simple. It is the extension point for
future priority, allocation, or planner-based task selection.

---

## 6. TransportTaskRunner

`task_runner.py` executes a `TransportItemTask` workflow.

It advances a task phase by phase and emits `ExecutionCommand`s for work that
must be executed externally.

For source-to-transfer, the normal flow is:

```text
LOAD_ITEM
ACQUIRE_DROPOFF
MOVE_TO_DROPOFF
UNLOAD_ITEM
DONE
```

For transfer-to-destination, the normal flow is:

```text
ACQUIRE_PICKUP
MOVE_TO_PICKUP
LOAD_ITEM
MOVE_TO_DROPOFF
UNLOAD_ITEM
DONE
```

The task runner updates `RuntimeWorld` when commands complete.

### Handling Occupied Transfer

If a robot needs the transfer resource and it is unavailable:

```text
can_acquire(transfer, robot, purpose, item) -> false
```

the task runner emits:

```text
MOVE_ROBOT(robot, staging)
```

and moves the task into:

```text
WAIT_FOR_RESOURCE
```

When the orchestrator ticks again and the resource can be acquired, the task
continues to the transfer waypoint.

This is the current explicit equivalent of a future BT fallback:

```text
Fallback
  Sequence
    AcquireResource
    NavigateToTransfer
  Sequence
    NavigateToStaging
    WaitForResource
    AcquireResource
    NavigateToTransfer
```

---

## 7. RuntimeWorld

`world.py` owns the runtime world model.

Main types:

```text
RuntimeWorld
WorldRobotState
WorldItemState
WorldRobotStatus
```

Robot state includes:

```text
robot_id
location
status
active_task_id
```

Item state includes:

```text
item_id
location
carried_by
```

`RuntimeWorld` provides operations for:

* checking robot availability
* checking item location
* assigning/releasing robots
* moving robots
* loading/unloading items
* acquiring/releasing resources through `WorldResourceManager`
* buffering/releasing items in resources

---

## 8. Resources

`resources.py` defines generic resources.

Main types:

```text
ResourceType
ResourceReservationStatus
ResourceReservation
ResourceState
```

The default transfer resource is:

```text
resource_id = transfer
resource_type = TRANSFER_ZONE
robot_capacity = 1
package_capacity = 1
```

`ResourceState` tracks:

```text
robot_occupancy
package_occupancy
reservations
```

The capacity helpers are:

```text
robot_slots_available
package_slots_available
```

These replace fixed transfer assumptions with resource capacity checks.

`WorldResourceManager` applies these rules:

```text
dropoff:
  robot slot must be available
  package slot must be available
  item_id must be present

pickup:
  robot slot must be available
  package occupancy must be non-empty
```

Reservations exist in the model, but the current task runner primarily uses
occupancy and buffer state. Reservation lifecycle can be expanded when concurrent
task execution requires stronger claims before navigation.

---

## 9. Execution Commands

`execution.py` defines concrete work commands.

Main types:

```text
ExecutionCommandType
ExecutionCommandStatus
ExecutionCommand
ExecutionManager
```

Current command types:

```text
MOVE_ROBOT
HANDLE_ITEM
```

Command statuses:

```text
PENDING
SUBMITTED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

The task runner creates commands through `ExecutionManager`.

`MOVE_ROBOT` is executed by RMF.

`HANDLE_ITEM` is simulated by a ROS timer for now.

---

## 10. RMF Execution Adapter

`rmf_execution_adapter.py` converts movement commands into RMF task API
requests.

It handles:

```text
ExecutionCommand(MOVE_ROBOT)
  -> RMF robot_task_request
```

It tracks:

```text
request_id -> command_id
rmf_task_id -> command_id
completed_rmf_task_ids
```

When RMF reports task completion, the node asks:

```text
command_from_completed_task(rmf_task_id)
```

and receives the command ID to complete in the orchestrator.

The adapter does not translate RMF completions into mission events. It only maps
RMF execution back to command lifecycle.

---

## 11. Handling Timer

Loading and unloading are represented as `HANDLE_ITEM` execution commands.

The current implementation is simulated:

```text
HANDLE_ITEM command
  -> MissionManagerNode starts 5 second ROS timer
  -> timer fires
  -> MissionManagerNode calls orchestrator.complete_command(command_id)
```

When a load command completes:

```text
item.carried_by = robot_id
item.location = robot current location
```

When an unload command completes:

```text
item.carried_by = None
item.location = task dropoff
```

If the dropoff is a resource such as `transfer`, the item is buffered there and
robot occupancy is released.

Later, a real robot/hardware confirmation can complete the same `HANDLE_ITEM`
command instead of the timer.

---

## 12. End-To-End Workflow

Initial state:

```text
mission status = READY
P1.location = source
tb3_1.location = robot1_home
tb3_2.location = robot2_home
transfer.robot_occupancy = []
transfer.package_occupancy = []
```

The operator starts the mission:

```text
MissionManagerNode
  -> MissionOrchestrator.start()
```

The orchestrator marks the mission running and asks the scheduler for a ready
task.

The scheduler selects:

```text
P1:source_to_transfer
```

The task runner starts the task. Since `tb3_1` starts at `robot1_home`, it emits:

```text
MOVE_ROBOT(tb3_1, source)
```

After RMF reports that movement complete, the task runner emits:

```text
HANDLE_ITEM(load P1 with tb3_1)
```

The node starts a handling timer. When it fires:

```text
orchestrator.complete_command(load_command_id)
```

The task runner updates:

```text
P1.carried_by = tb3_1
```

Then it acquires the transfer resource for dropoff and emits:

```text
MOVE_ROBOT(tb3_1, transfer)
```

RMF executes the movement. When RMF reports completion, the node maps the RMF
task ID back to the command ID and calls:

```text
orchestrator.complete_command(move_command_id)
```

The task runner updates:

```text
tb3_1.location = transfer
```

Then it emits:

```text
HANDLE_ITEM(unload P1 from tb3_1)
```

When the unload timer completes:

```text
P1.location = transfer
P1.carried_by = None
transfer.package_occupancy = [P1]
transfer.robot_occupancy = []
P1:source_to_transfer.status = SUCCEEDED
```

The orchestrator ticks again. The scheduler now sees that `P1` is at `transfer`
and selects:

```text
P1:transfer_to_destination
```

The downstream task moves `tb3_2` to transfer, loads `P1`, moves to destination,
and unloads it.

Final state:

```text
P1.location = destination
P1.carried_by = None
all transportItem tasks = SUCCEEDED
mission status = COMPLETED
```

---

## 13. Current Extension Points

The current implementation is intentionally small, but the boundaries are in
place:

* `TransportTaskScheduler` can be replaced with priority, allocation, or planner
  output.
* `TransportTaskRunner` can be replaced by or wrapped with a behavior tree
  executor.
* `WorldResourceManager` can grow stronger reservation and concurrency rules.
* `RmfExecutionAdapter` can add cancellation/failure handling and richer command
  types.
* `HANDLE_ITEM` timers can be replaced by real load/unload confirmations.

The current architecture is designed around a clear split:

```text
Mission policy:
  MissionOrchestrator, TransportTaskScheduler, TransportTaskRunner

World truth:
  RuntimeWorld, WorldResourceManager, ResourceState

Execution lifecycle:
  ExecutionManager, ExecutionCommand

External adapters:
  MissionManagerNode, RmfExecutionAdapter, handling timers

State output:
  mission_serializer.py
```

The important rule is that mission decisions happen in the core runtime, while
ROS and RMF are adapters around that core. This keeps the mission logic testable
without running ROS and keeps RMF task IDs out of the task model.
