# Mission Layer Current Architecture

This document describes the current `mission_manager` implementation. The
system is a centralized mission-control layer above Open-RMF / Free Fleet:

```text
Central mission layer:
  package workflow, robot roles, transfer resource rules, mission state

Open-RMF / Free Fleet:
  traffic-aware waypoint execution, fleet state, Nav2 command dispatch

Robot PCs:
  TurtleBot3 hardware, localization, Nav2, Zenoh ROS 2 bridge
```

The active mission is a fixed two-robot handoff:

```text
source -> transfer -> destination

tb3_1 moves packages from source to transfer
tb3_2 moves packages from transfer to destination
```

The mission layer treats this as transport task instances rather than a single
large fixed FSM.

---

## Runtime Flow

The active runtime path is:

```text
MissionManagerNode
  -> MissionManager
  -> TransportTaskScheduler
  -> TransportTaskBtRunner
  -> ExecutionManager
  -> RmfAdapter / robot handling simulator
  -> execution completion
  -> MissionManager
```

The main split is:

```text
MissionManagerNode:
  ROS I/O, RMF subscriptions, execution-result subscriptions, mission_state publication

MissionManager:
  mission lifecycle, task coordination, command completion handling

TransportTaskScheduler:
  selects the next pending task that is allowed to start

TransportTaskBtRunner:
  executes one transport task using a small behavior-tree sequence

MissionWorld:
  mission-layer belief about robots, items, and resources

ResourceManager:
  resource access, transfer leases, occupancy, and package buffering

ExecutionManager:
  creates and tracks execution commands

RmfAdapter:
  converts move commands into RMF task API requests
```

Source map:

```text
mission_manager_node.py       ROS node, topics, RMF/free_fleet callbacks
mission_manager.py            mission lifecycle and task coordination
mission_tasks.py              mission/task status and transport task model
scheduler.py                  deterministic ready-task selection and pre-staging
behavior_tree.py              minimal BT primitives
transport_bt_runner.py        transport task BT executor
world.py                      robot/item/resource runtime state facade
world_resource_manager.py     transfer access, lease, occupancy, buffer rules
resources.py                  resource state model
execution.py                  execution command lifecycle
rmf_adapter.py                RMF task API adapter for movement commands
mission_serializer.py         mission_state JSON serialization
robot_bringup/handling_simulator_node.py
                             robot-side simulated load/unload confirmation
```

---

## Default Mission Model

`MissionManager.create_default(...)` creates two tasks per package:

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
transfer.wait_waypoints = {
  tb3_1: upstream_exit
  tb3_2: downstream_exit
}
```

The transfer zone is the only managed mission resource. Directional exit
waypoints double as safe wait/clear points:

```text
tb3_1 waits or clears at upstream_exit
tb3_2 waits or clears at downstream_exit
```

There is still a `staging` waypoint in the map assets, but it is no longer part
of the active mission logic.

---

## RMF Graph Semantics

The active RMF navigation graph is intentionally constrained to the mission
corridor:

```text
robot1_home <-> source
source <-> upstream_exit
upstream_exit <-> transfer      mutex: transfer_zone
transfer <-> downstream_exit    mutex: transfer_zone
downstream_exit <-> destination
destination <-> robot2_home
```

Only the lanes that enter or leave the transfer conflict area use the
`transfer_zone` mutex:

```text
upstream_exit <-> transfer
transfer <-> downstream_exit
```

The mission layer decides which robot may use transfer. RMF graph design and
mutexes help the physical movement respect that decision.

---

## Mission Orchestrator

`mission_manager.py` owns the mission runtime.

`MissionRuntime` holds:

```text
mission_id
mission status
transport task instances
MissionWorld
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

The mission manager does not publish ROS messages or RMF requests directly. It
returns `ExecutionCommand` objects to the ROS node.

---

## Scheduler

`TransportTaskScheduler` chooses the next ready `TransportItemTask`.

Current readiness checks:

```text
task.status == PENDING
task.robot_id is assigned
assigned robot is IDLE
item is physically at task.pickup
managed pickup resource is available
```

There is one pre-staging exception: a task may start early if its pickup is a
managed resource with a robot-specific wait waypoint and the item is currently
being carried. This lets `tb3_2` move to `downstream_exit` while `tb3_1` is
carrying the package toward transfer, but `tb3_2` still cannot enter transfer
until the resource manager grants pickup access.

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
  MarkResourceOccupied(pickup)
  HandleItem(load)
  UpdateResourceAfterHandling(pickup, load)
  VacateResourceIfManaged(pickup)
  ReleaseResourceIfManaged(pickup)
  RequestResourceAccess(dropoff)
  MoveTo(dropoff)
  MarkResourceOccupied(dropoff)
  HandleItem(unload)
  UpdateResourceAfterHandling(dropoff, unload)
  VacateResourceIfManaged(dropoff)
  ReleaseResourceIfManaged(dropoff)
  ReleaseRobot
  MarkTaskSucceeded
```

The BT emits commands instead of executing work directly:

```text
MoveTo(...)
  -> ExecutionCommand(MOVE_ROBOT)

HandleItem(...)
  -> ExecutionCommand(HANDLE_ITEM)
```

World state is updated after command completion:

```text
MOVE_ROBOT succeeded:
  world.move_robot(robot_id, target)

HANDLE_ITEM load succeeded:
  world.load_item(robot_id, item_id)

HANDLE_ITEM unload succeeded:
  world.unload_item(robot_id, item_id, task.dropoff)
```

For managed resources, package and resource state changes happen near the
physical event that justifies them:

```text
downstream load from transfer:
  remove item from transfer buffer
  move to downstream_exit
  release transfer occupancy and lease
  continue to destination

upstream unload into transfer:
  buffer item at transfer
  move to upstream_exit
  release transfer occupancy and lease
  mark upstream task succeeded
```

---

## Resource Access

`ResourceManager.request_access(...)` is the resource-access gate.

Current transfer rules:

```text
dropoff into transfer:
  no other active lease holder
  robot slot must be available
  package slot must be available
  item_id must be present

pickup from transfer:
  no other active lease holder
  robot slot must be available
  requested item must already be buffered in transfer
```

If access is granted:

```text
status = GRANTED
target = transfer
active_lease = robot / task / purpose / package
```

If access is unavailable and the robot has a configured wait waypoint:

```text
status = WAIT
target = upstream_exit or downstream_exit
reason = PACKAGE_NOT_AVAILABLE | TRANSFER_PACKAGE_FULL | TRANSFER_ROBOT_OCCUPIED | ...
```

If access cannot be granted and no wait target exists:

```text
status = BLOCKED
```

The BT handles `WAIT` by moving the robot to its directional wait waypoint,
marking the task as blocked, and retrying resource access when the mission
advances.

The resource state tracks:

```text
active_lease
robot_occupancy
package_occupancy
wait_waypoints
```

`active_lease` plus occupancy is the current coordination mechanism.

---

## ROS, RMF, And Execution Boundary

`MissionManagerNode` is the ROS shell.

It subscribes to:

```text
mission_commands
task_api_responses
task_summaries
mission_execution_results
```

It publishes:

```text
task_api_requests
mission_state
mission_execution_commands
```

Command dispatch:

```text
MOVE_ROBOT:
  publish mission_execution_commands context
  RmfAdapter.submit_command(...)
  publish robot_task_request to task_api_requests

HANDLE_ITEM:
  publish mission_execution_commands context
  wait for robot-side handling result
```

`RmfAdapter` converts movement commands into RMF
`robot_task_request` payloads. Movement is currently requested as a composed
`go_to_place` task:

```text
category = compose
phase activity = go_to_place
target waypoint = command.target
```

The adapter tracks:

```text
request_id -> command_id
rmf_task_id -> command_id
completed_rmf_task_ids
```

---

## Handling Completion Path

`HANDLE_ITEM` commands are not RMF tasks. The mission manager publishes them on
`mission_execution_commands` and waits for a robot-side result:

```text
MissionManagerNode publishes HANDLE_ITEM command context
handling_simulator_node filters by robot_id
handling_simulator_node waits handling_duration_sec
handling_simulator_node publishes mission_execution_results
MissionManagerNode calls mission_manager.complete_command(command_id)
```

The command payload includes:

```text
mission_id
command_id
task_id
robot_id
command_type = handle_item
item_id
handling_type = load | unload
```

The current simulator always reports `SUCCEEDED` after the configured delay. It
is a robot-side stand-in for a future actuator, sensor, operator confirmation,
or simulator-truth confirmation source. During the delay it may call the
TurtleBot3 `sound` service for observable start/end cues, but sound feedback is
best-effort and does not decide command success.

---

## Movement Completion Paths

Movement completion can reach the mission manager through multiple paths.

Primary path:

```text
MissionManagerNode publishes mission_execution_commands
free_fleet Nav2 adapter attaches the command context to the next navigation goal
Nav2 reports the goal succeeded
free_fleet Nav2 adapter publishes mission_execution_results
MissionManagerNode calls mission_manager.complete_command(command_id)
```

Secondary path:

```text
task_summaries:
  RMF task summary reports STATE_COMPLETED
  mission node maps rmf_task_id -> command_id
```

The mission layer no longer completes commands from inferred `/fleet_states`
pose or mode. Movement completion should come from explicit execution results
or RMF task summaries.

Expected direct completion logs:

```text
Published mission execution result: {... "status": "SUCCEEDED", "source": "nav2_result" ...}
Mission command completed from nav2_result: cmd_X
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
transfer.active_lease = None
```

Normal one-package flow:

```text
1. Scheduler starts P1:source_to_transfer.
2. tb3_1 moves to source.
3. tb3_1 loads P1.
4. tb3_1 requests transfer dropoff access.
5. If transfer is free, tb3_1 moves to transfer via upstream_exit.
6. If transfer is blocked, tb3_1 waits at upstream_exit with a blocked reason.
7. tb3_1 unloads P1 at transfer.
8. P1 is buffered in transfer.
9. tb3_1 moves to upstream_exit.
10. Transfer occupancy and lease are released.
11. P1:source_to_transfer succeeds.
12. Scheduler starts or resumes P1:transfer_to_destination.
13. tb3_2 requests transfer pickup access.
14. If P1 is buffered and transfer is free, tb3_2 enters transfer via downstream_exit.
15. Otherwise tb3_2 waits at downstream_exit with a blocked reason.
16. tb3_2 loads P1.
17. P1 is removed from transfer buffer.
18. tb3_2 moves to downstream_exit.
19. Transfer occupancy and lease are released.
20. tb3_2 moves to destination.
21. tb3_2 unloads P1.
22. P1:transfer_to_destination succeeds.
23. Mission completes when all transport tasks succeed.
```

Current mission completion does not explicitly send robots home. Return-home
behavior should be added as explicit mission-layer behavior if needed.

---

## Current Design Constraints

The mission layer controls logical mission rules:

```text
which task can start
whether a robot may enter transfer
whether a package is available for pickup
which directional wait point a robot should use
when a task succeeds
```

RMF controls traffic and navigation execution:

```text
route planning on the RMF graph
traffic negotiation
robot task execution
fleet state reporting
Nav2 command dispatch through free_fleet
```

Those layers are complementary. RMF does not understand the package-transfer
rule unless the mission layer, RMF graph design, mutexes, or task definitions
encode it.

The current mission world is still optimistic for package handling: it updates
item state when robot-side handling simulator results arrive. It does not yet
verify physical package pickup/dropoff.

---

## Extension Points

Current extension points:

```text
TransportTaskScheduler:
  priority, fairness, robot allocation, pre-staging policy

TransportTaskBtRunner:
  richer task behavior, retry/recovery, alternative BT backend

ResourceManager:
  queues, stronger lease arbitration, timeouts

RmfAdapter:
  cancellation, failure handling, richer RMF task types

MissionManagerNode:
  replace robot-side handling simulation with real hardware confirmations
  strengthen execution-result failure/cancellation handling

MissionManager:
  explicit return-home behavior, pause/resume/abort semantics
```

See `docs/mission_layer_strengthening_suggestions.md` for recommended next
improvements.
