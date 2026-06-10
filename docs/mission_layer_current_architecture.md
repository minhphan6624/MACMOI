# Mission Layer Current Architecture

This document describes the current `mrd_mission_manager` implementation. The
mission layer is a small task orchestration system around package transport,
runtime world state, resource access, behavior-tree task execution, and an RMF
movement adapter.

The active mission is still the two-robot handoff:

```text
source -> transfer -> destination

tb3_1 moves packages from source to transfer
tb3_2 moves packages from transfer to destination
```

The old fixed mission FSM path has been removed from the active runtime. The
current implementation represents the handoff as transport task instances.

---

## Runtime Flow

The active runtime path is:

```text
MissionManagerNode
  -> MissionOrchestrator
  -> TransportTaskScheduler
  -> TransportTaskBtRunner
  -> ExecutionManager
  -> RmfExecutionAdapter / handling timer
  -> command completion
  -> MissionOrchestrator
```

The main split is:

```text
MissionManagerNode:
  ROS I/O, timers, RMF subscriptions, mission_state publication

MissionOrchestrator:
  mission lifecycle, task coordination, command completion handling

TransportTaskScheduler:
  selects the next pending task that is allowed to start

TransportTaskBtRunner:
  executes one transport task using a small behavior-tree sequence

RuntimeWorld:
  mission-layer belief about robots, items, and resources

WorldResourceManager:
  resource access decisions, occupancy, and transfer package buffering

ExecutionManager:
  creates and tracks execution commands

RmfExecutionAdapter:
  converts move commands into RMF task API requests
```

Source map:

```text
mission_manager_node.py       ROS node, topics, timers, RMF subscriptions
orchestrator.py               mission lifecycle and task coordination
mission_tasks.py              mission/task status and transport task model
scheduler.py                  deterministic ready-task selection
behavior_tree.py              minimal BT primitives
transport_bt_runner.py        transport task BT executor
world.py                      robot/item/resource runtime state facade
world_resource_manager.py     resource access and buffer rules
resources.py                  resource state model
execution.py                  execution command lifecycle
rmf_execution_adapter.py      RMF task API adapter for movement commands
mission_serializer.py         mission_state JSON serialization
```

---

## Default Mission Model

`MissionOrchestrator.create_default(...)` creates two tasks per package:

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

For `N` packages, the runtime creates `2N` transport tasks.

The default world starts as:

```text
tb3_1.location = robot1_home
tb3_2.location = robot2_home
P1.location = source
transfer.robot_capacity = 1
transfer.package_capacity = 1
transfer.wait_waypoint = staging
```

The transfer zone is the only managed resource in the default mission. It is
managed at the mission layer for logical access control, while RMF still handles
traffic planning and navigation execution.

---

## Mission Orchestrator

`orchestrator.py` owns the mission runtime.

`MissionRuntime` holds:

```text
mission_id
mission status
transport task instances
RuntimeWorld
```

The orchestrator owns:

```text
TransportTaskScheduler
TransportTaskBtRunner
ExecutionManager
```

Main behavior:

```text
start()
  set READY -> RUNNING
  tick()

tick()
  if all tasks succeeded, mark mission COMPLETED
  advance any RUNNING or BLOCKED task
  otherwise ask scheduler for a ready PENDING task
  start the selected task through the BT runner

complete_command(command_id)
  mark command succeeded
  let BT runner update world state
  advance the task
  optionally start another ready task
```

The orchestrator does not publish ROS messages or RMF requests directly. It only
returns `ExecutionCommand` objects.

---

## Scheduler

`TransportTaskScheduler` chooses the next ready `TransportItemTask`.

Current readiness checks:

```text
task.status == PENDING
task.robot_id is assigned
assigned robot is IDLE
item is physically at task.pickup
```

There is one exception: a task may start early if its pickup is a managed
resource with a wait waypoint and the item is currently being carried. This is
used for downstream pickup at `transfer`: `tb3_2` can move to `staging` while
`tb3_1` is carrying the package toward transfer, but it should not enter
transfer until the resource manager grants pickup access.

The scheduler is deterministic and simple. It sorts task IDs and picks the first
eligible task.

---

## Behavior Tree Runner

`TransportTaskBtRunner` executes one `TransportItemTask`.

The current tree is:

```text
MemorySequence transport_item
  AssignRobot
  RequestResourceAccess(pickup)
  MoveTo(pickup)
  HandleItem(load)
  ReleasePickupItemIfManaged
  RequestResourceAccess(dropoff)
  MoveTo(dropoff)
  ReleaseResourceOccupancyIfManaged(pickup)
  HandleItem(unload)
  VacateDropoffIfNeeded
  ReleaseResourceIfManaged(dropoff)
  ReleaseRobot
  MarkTaskSucceeded
```

The BT is intentionally small. `MemorySequence` stores the current child index
in `task.bt_blackboard`, so each tick resumes from the current step instead of
restarting from the beginning.

The BT emits commands instead of executing work directly:

```text
MoveTo(...)
  -> ExecutionCommand(MOVE_ROBOT)

HandleItem(...)
  -> ExecutionCommand(HANDLE_ITEM)
```

World state is updated only after command completion:

```text
MOVE_ROBOT succeeded:
  world.move_robot(robot_id, target)

HANDLE_ITEM load succeeded:
  world.load_item(robot_id, item_id)

HANDLE_ITEM unload succeeded:
  world.unload_item(robot_id, item_id, task.dropoff)
```

---

## Resource Access

`WorldResourceManager.request_access(...)` is the resource-access gate.

Current transfer rules:

```text
dropoff into transfer:
  robot slot must be available
  package slot must be available
  item_id must be present

pickup from transfer:
  robot slot must be available
  requested item must already be buffered in transfer
```

If access is granted:

```text
status = GRANTED
target = transfer
```

If access is unavailable but the resource has a wait waypoint:

```text
status = WAIT
target = staging
```

If access cannot be granted and no wait waypoint exists:

```text
status = BLOCKED
```

The BT handles `WAIT` by moving the robot to `staging`, marking the task as
blocked, and retrying resource access on later ticks.

The resource state tracks:

```text
robot_occupancy
package_occupancy
reservations
```

Reservations exist in the model but are not yet the main coordination mechanism.
The current behavior primarily uses occupancy and transfer package buffering.

---

## ROS and RMF Boundary

`MissionManagerNode` is the ROS shell.

It subscribes to:

```text
mission_commands
task_api_responses
task_summaries
fleet_states
```

It publishes:

```text
task_api_requests
mission_state
```

Command dispatch:

```text
MOVE_ROBOT:
  RmfExecutionAdapter.submit_command(...)
  publish robot_task_request to task_api_requests

HANDLE_ITEM:
  start a 5 second ROS timer
  complete the command when the timer fires
```

`RmfExecutionAdapter` converts movement commands into RMF
`robot_task_request` payloads. It tracks:

```text
request_id -> command_id
rmf_task_id -> command_id
completed_rmf_task_ids
```

When RMF reports a task completion, the node maps the RMF task ID back to the
mission command ID and calls:

```text
orchestrator.complete_command(command_id)
```

---

## End-to-End Package Flow

Initial state:

```text
mission = READY
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

Normal one-package flow:

```text
1. Scheduler starts P1:source_to_transfer.
2. tb3_1 moves to source.
3. tb3_1 loads P1.
4. tb3_1 requests transfer dropoff access.
5. If transfer is free, tb3_1 moves to transfer.
6. If transfer is blocked, tb3_1 moves to staging and waits.
7. tb3_1 unloads P1 at transfer.
8. P1 is buffered in transfer.
9. tb3_1 vacates transfer back toward source.
10. P1:source_to_transfer succeeds.
11. Scheduler starts or resumes P1:transfer_to_destination.
12. tb3_2 requests transfer pickup access.
13. If P1 is buffered and transfer robot slot is free, tb3_2 enters transfer.
14. Otherwise tb3_2 waits at staging.
15. tb3_2 loads P1.
16. P1 is removed from transfer buffer.
17. tb3_2 moves to destination.
18. tb3_2 unloads P1.
19. P1:transfer_to_destination succeeds.
20. Mission completes when all transport tasks succeed.
```

Current mission completion does not explicitly send robots home. Return-home
behavior is still expected from RMF/fleet adapter finishing behavior or should
be added as explicit mission-layer behavior in a future change.

---

## Current Design Constraints

The mission layer controls logical mission rules:

```text
which task can start
whether a robot may enter transfer
whether a package is available for pickup
which robot should wait at staging
when a task succeeds
```

RMF controls traffic and navigation execution:

```text
route planning
traffic negotiation
robot task execution
fleet state reporting
```

Those layers are complementary. RMF does not understand the package-transfer
rule unless the mission layer, RMF mutexes, graph design, or task definitions
encode it.

The current mission world is also optimistic: it updates robot and item state
when commands are reported complete. It does not continuously verify physical
robot pose or package handling state.

---

## Extension Points

Current extension points:

```text
TransportTaskScheduler:
  priority, fairness, robot allocation, pre-staging policy

TransportTaskBtRunner:
  richer task behavior, retry/recovery, alternative BT backend

WorldResourceManager:
  reservations, queues, stronger multi-robot resource arbitration

RmfExecutionAdapter:
  cancellation, failure handling, richer RMF task types

MissionManagerNode:
  replace handling timers with real robot/hardware confirmations

MissionOrchestrator:
  explicit return-home behavior, pause/resume/abort semantics
```

See `docs/mission_layer_strengthening_suggestions.md` for the recommended next
improvements.
