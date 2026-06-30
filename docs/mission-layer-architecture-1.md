# Mission Layer Architecture Analysis

## 1. Executive Summary

The mission layer is a centralized, event-driven mission orchestrator above
Open-RMF and Free Fleet.

It does not perform path planning or directly control robots. It owns the
higher-level workflow:

- which robot performs each package leg
- when a task may start
- package ownership and logical location
- exclusive access to the transfer zone
- task and mission lifecycle
- pause, resume, abort, retry, and failure handling
- translation of mission decisions into external execution commands

Open-RMF and Free Fleet remain responsible for traffic-aware navigation and Nav2
execution.

The implemented mission is a fixed two-robot package pipeline:

```text
tb3_1                         tb3_2
source --------> transfer --------> destination
       package handoff
```

For every package, the manager creates two transport tasks:

```text
P1:source_to_transfer
P1:transfer_to_destination
```

Architecturally, the implementation combines:

- an in-memory domain model
- hierarchical state machines
- a small behavior tree for task execution
- command/event separation
- lease-based resource coordination
- adapter-based integration with ROS 2 and RMF

The package is under `rmf_ws/src/mission_manager/mission_manager`.

## 2. System Context

The mission layer sits between operator-facing systems and the robot execution
stack:

```text
Operator / Web UI
        |
        | mission_commands
        v
+-------------------------------+
| MissionManagerNode            |  ROS integration shell
|                               |
| - translates ROS messages     |
| - publishes state/events      |
| - dispatches commands         |
| - validates execution results |
+---------------+---------------+
                | domain events
                v
+-------------------------------+
| MissionManager                |  Application/orchestration layer
|                               |
| - mission lifecycle           |
| - event handling              |
| - scheduling                  |
| - retries/failures            |
+-------+-----------+-----------+
        |           |
        v           v
+--------------+  +-----------------------+
| Scheduler    |  | TransportTaskRunner |
|              |  |                       |
| chooses work |  | executes task steps   |
+--------------+  +-----------+-----------+
                            |
                +-----------+------------+
                v                        v
+------------------------+  +-----------------------+
| MissionWorld           |  | ExecutionManager      |
|                        |  |                       |
| robots/packages/zones  |  | external command FSM  |
+-----------+------------+  +-----------+-----------+
            v                           v
+------------------------+  +-----------------------+
| ResourceManager        |  | RmfAdapter / ROS      |
| leases and capacities  |  | execution adapters    |
+------------------------+  +-----------------------+
```

The central ownership boundary is:

```text
Mission domain:
  decides what should happen

ROS/RMF adapters:
  arrange for it to happen and report the result
```

This resembles a ports-and-adapters architecture, although the ports are
concrete Python APIs rather than formal abstract interfaces.

## 3. Main Components

| Component | Source | Responsibility |
|---|---|---|
| `MissionManagerNode` | `mission_manager_node.py` | ROS 2 I/O and infrastructure integration |
| `MissionManager` | `mission_manager.py` | Mission lifecycle and top-level orchestration |
| `MissionRuntime` | `mission_manager.py` | Root in-memory mission state |
| `TransportTaskScheduler` | `scheduler.py` | Selects eligible pending tasks |
| `TransportTaskRunner` | `transport_task_runner.py` | Runs the transport workflow |
| `MissionWorld` | `world.py` | Mission-layer belief state |
| `ResourceManager` | `world_resource_manager.py` | Transfer-zone arbitration |
| `ExecutionManager` | `execution_manager.py` | Creates and tracks external commands |
| `RmfAdapter` | `rmf_adapter.py` | Maps movement commands to RMF task requests |
| Mission serializers | `mission_serializer.py` | Build operator and debug read models |

### 3.1 ROS integration shell

`MissionManagerNode` is the package's infrastructure boundary. It:

- instantiates the default mission
- subscribes to operator, RMF, and execution-result topics
- converts messages into domain events
- passes events to `MissionManager`
- dispatches returned execution commands
- publishes mission state, debug state, and event history

The core mission manager does not import ROS. This keeps most mission behavior
independent of the ROS runtime.

### 3.2 Mission orchestrator

`MissionManager` is the application service and central coordinator. Its primary
interface is:

```python
commands = mission_manager.handle_event(event)
```

It consumes an event, mutates mission state, advances active tasks, schedules
new tasks, and returns zero or more `ExecutionCommand` objects. It does not
execute those commands itself.

## 4. Domain Model

The aggregate root is `MissionRuntime`:

```text
MissionRuntime
|-- mission_id
|-- MissionStatus
|-- tasks: dict[task_id, TransportItemTask]
`-- MissionWorld
    |-- robots
    |-- items
    `-- managed resources
```

### 4.1 Mission lifecycle

The high-level mission lifecycle is:

```text
READY --start--> RUNNING --all tasks succeed--> COMPLETED
                   |
                   |--pause--> PAUSED --resume--> RUNNING
                   |--fatal command error--> FAILED
                   `--abort--> ABORTED
```

The status model also contains `CREATED`, although the default factory creates
missions directly in `READY`.

### 4.2 Transport-task lifecycle

Each `TransportItemTask` has a lifecycle status:

```text
PENDING
RUNNING
BLOCKED
SUCCEEDED
FAILED
CANCELLED
```

It also records its current workflow phase:

```text
NOT_STARTED
ACQUIRE_PICKUP
MOVE_TO_PICKUP
LOAD_ITEM
ACQUIRE_DROPOFF
MOVE_TO_WAIT_POINT
WAIT_FOR_RESOURCE
MOVE_TO_DROPOFF
UNLOAD_ITEM
MOVE_TO_TRANSFER_EXIT
DONE
```

Additional task state includes:

- assigned robot
- active command ID
- resource being waited for
- blocking reason and blocking actor
- current wait waypoint
- unblock condition
- expected next event
- behavior-tree blackboard

The lifecycle status describes whether the task can progress, while the phase
describes where it is inside the transport workflow.

### 4.3 Mission-world belief state

`MissionWorld` is the mission layer's logical view of the environment. It is not
raw RMF or Nav2 telemetry.

`RobotState` contains:

```text
logical waypoint
IDLE / BUSY / WAITING status
active task
pause state
requested and confirmed speed scale
```

`PackageState` contains:

```text
logical location
carrying robot, if any
```

World changes are applied after execution results are accepted. A successful
move updates the robot's logical waypoint. A successful load or unload updates
package ownership and location.

The world is therefore a belief-state model derived from accepted results, not
a continuously reconciled digital twin.

## 5. Default Mission Construction

`MissionManager.create_default(...)` builds the fixed two-robot mission.

For `N` packages it creates:

```text
N packages
2N transport tasks
2 fixed-role robots
1 managed transfer resource
```

The roles and important waypoints are defined in `mission_definition.py`:

```text
tb3_1: upstream robot
tb3_2: downstream robot

source
transfer
destination
upstream_exit
downstream_exit
```

For each package:

```text
source_to_transfer:
  robot = tb3_1
  pickup = source
  dropoff = transfer

transfer_to_destination:
  robot = tb3_2
  pickup = transfer
  dropoff = destination
```

The transfer resource is initialized with:

```text
robot_capacity   = 1
package_capacity = 1

wait points:
  tb3_1 -> upstream_exit
  tb3_2 -> downstream_exit
```

Source and destination are ordinary waypoints. Only `transfer` is managed as a
constrained mission resource.

## 6. Scheduling Model

`TransportTaskScheduler` performs deterministic readiness selection. It sorts
task IDs and returns the first task satisfying:

- task status is `PENDING`
- a robot is assigned
- the robot is idle and not paused
- the package is at the pickup point, or pre-staging is allowed
- a managed pickup resource is available when the package is already there

The pre-staging exception permits a downstream task to start while its package
is still being carried toward transfer. The downstream robot can move to
`downstream_exit`, but it cannot enter transfer until the package is buffered
and the resource lease is granted.

This permits limited cooperative concurrency:

```text
tb3_1 transports P1 toward transfer
tb3_2 moves to its transfer-side waiting point
```

The scheduler is not a general optimization engine. It has no priority, dynamic
robot allocation, deadline, cost, or fairness policy beyond sorted task IDs.

## 7. Behavior-Tree Execution

`TransportTaskRunner` executes each transport task through one fixed
`MemorySequence`:

```text
AssignRobot
RequestResourceAccess(pickup)
MoveTo(pickup)
MarkResourceOccupied(pickup)
HandleItem(load)
UpdateResourceAfterHandling(pickup)
VacateResourceIfManaged(pickup)
ReleaseResourceIfManaged(pickup)

RequestResourceAccess(dropoff)
MoveTo(dropoff)
MarkResourceOccupied(dropoff)
HandleItem(unload)
UpdateResourceAfterHandling(dropoff)
VacateResourceIfManaged(dropoff)
ReleaseResourceIfManaged(dropoff)

ReleaseRobot
MarkTaskSucceeded
```

### 7.1 Memory sequence

`MemorySequence`:

- ticks children in order
- records the current child index in the task blackboard
- continues through immediately successful children
- stops when a child returns `RUNNING`
- resumes at the unfinished child on the next advancement

The custom BT supports only `SUCCESS` and `RUNNING`. It does not have a BT-level
`FAILURE` result. Execution failures are handled by `MissionManager` and stored
in task and mission state.

### 7.2 Asynchronous command nodes

`MoveTo` and `HandleItem` create commands rather than performing work:

```text
MoveTo
  -> ExecutionCommand(MOVE_ROBOT)

HandleItem
  -> ExecutionCommand(HANDLE_ITEM)
```

The node stores the emitted command ID as `task.active_command_id` and returns
`RUNNING`.

When the matching completion event arrives:

1. The execution command is marked succeeded.
2. The task's active command is cleared.
3. The runner updates the mission world.
4. The behavior tree resumes from its stored position.
5. The next command is emitted, or the task completes.

This is cooperative, asynchronous BT execution rather than a continuously
ticking robotics behavior tree.

## 8. Transfer Resource Coordination

`ResourceManager` provides logical mutual exclusion for the transfer zone.

A resource separates three related concepts:

```text
active_lease:
  permission and intent to use the resource

robot_occupancy:
  robots logically inside the resource

package_occupancy:
  packages buffered in the resource
```

### 8.1 Dropoff access

To drop a package at transfer:

- another robot must not hold the active lease
- a robot slot must be available
- a package slot must be available
- the request must identify the package

### 8.2 Pickup access

To pick a package up from transfer:

- another robot must not hold the active lease
- a robot slot must be available
- the requested package must be in `package_occupancy`

### 8.3 Access decisions

Resource requests return one of:

```text
GRANTED
WAIT
BLOCKED
```

`WAIT` contains a safe directional waypoint. The BT moves the robot there and
records an explanatory blocker, including:

```text
PACKAGE_NOT_AVAILABLE
TRANSFER_PACKAGE_FULL
TRANSFER_ROBOT_OCCUPIED
WAITING_FOR_TRANSFER_LEASE
```

If no wait waypoint is configured, an unavailable request becomes `BLOCKED`.

The lease is acquired before entering transfer. After load or unload, the robot
moves to its side-specific exit waypoint. Only then are robot occupancy and the
lease released.

For an upstream unload:

```text
unload package at transfer
buffer package in transfer resource
move robot to upstream_exit
release robot occupancy and lease
```

For a downstream load:

```text
load package from transfer
remove package from transfer resource
move robot to downstream_exit
release robot occupancy and lease
```

This prevents two robots from entering the transfer conflict area and prevents
the upstream robot from dropping a package into a full transfer buffer.

## 9. Event-Driven Command Loop

The central runtime loop is:

```text
incoming event
    |
    v
MissionManager.handle_event()
    |
    v
mutate mission/task/world state
    |
    v
advance behavior trees and scheduler
    |
    v
return ExecutionCommand objects
    |
    v
MissionManagerNode dispatches commands
    |
    v
external execution result
    |
    `----> new event
```

Domain events include:

- mission start
- mission pause and resume
- robot pause and resume
- mission abort
- execution completion
- execution failure
- execution cancellation
- retry metadata
- RMF task-summary completion observations

The design resembles CQRS in a limited sense:

- commands express requested side effects
- events report outcomes
- serialized mission state is an operator-facing read model

It is not full CQRS or event sourcing. State is mutable, and events are neither
persisted nor replayed to rebuild the runtime.

## 10. Mission Advancement

`MissionManager._advance()` is the mission's progression engine:

1. It returns immediately unless the mission is `RUNNING`.
2. It marks the mission `COMPLETED` if every task succeeded.
3. It ticks all `RUNNING` and `BLOCKED` tasks that are not robot-paused.
4. If a task emits an execution command, it may also start one additional ready
   task.
5. If no active task emits work, it asks the scheduler for the next ready
   pending task.

Blocked tasks are reconsidered when `_advance()` is called by another event.
There is no dedicated resource-event subscription or periodic mission tick in
the core.

Because robot roles are fixed and each robot can own only one task, practical
parallelism is limited to one active task per robot.

## 11. Execution Command Lifecycle

`ExecutionManager` creates and tracks commands using:

```text
PENDING
SUBMITTED
RUNNING
SUCCEEDED
FAILED
CANCELLED
```

Commands carry:

```text
command_id
command_type
task_id
robot_id
target
item_id
handling_type
status
error
```

Terminal transitions are idempotent: a completed, failed, or cancelled command
cannot be transitioned again.

Command IDs are generated in memory as `cmd_1`, `cmd_2`, and so on. They are
unique only within one process lifetime.

## 12. RMF and Robot Integration

### 12.1 Movement dispatch

`RmfAdapter` converts `MOVE_ROBOT` commands into an RMF composed
`go_to_place` request:

```text
robot_task_request
  category = compose
  phase activity = go_to_place
  target = command.target
```

It correlates identifiers using:

```text
RMF request ID -> mission command ID
RMF task ID    -> mission command ID
completed RMF task IDs
```

`MissionManagerNode` also publishes each command on
`mission_execution_commands`. The Free Fleet adapter uses this command context
to associate the subsequent RMF navigation execution with the mission command.

### 12.2 Movement completion

RMF task-summary completion is recorded for lifecycle and debugging visibility,
but it does not complete the mission command.

Actual movement completion comes from the Free Fleet/Nav2 side over
`mission_execution_results`. The mission node accepts movement success only
when:

- the source is `nav2_result` or `nav2_already_near_target`
- `arrival_verified` is explicitly `true`

This prevents a lossy RMF lifecycle signal from advancing package handling
before physical arrival has been verified.

An `arrival_not_verified` failure is retried up to two times by default. After
the retry limit, or for other execution failures, the task and mission become
`FAILED`.

### 12.3 Package handling

`HANDLE_ITEM` is not submitted as an RMF task. It is published through
`mission_execution_commands`, marked submitted and running, and waits for an
external result.

The mission package does not contain the handling executor. Another robot-side,
simulation, actuator, sensor, or operator component must report the handling
result on `mission_execution_results`.

Only after a successful result does the mission world logically load or unload
the package.

## 13. ROS Topics

`MissionManagerNode` subscribes to:

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
mission_debug_state
mission_events
mission_execution_commands
```

`mission_execution_commands` is used for:

- move-command context
- package handling commands
- movement cancellation
- per-robot pause and resume
- robot speed-scale changes

## 14. Operator Control

### 14.1 Mission pause and resume

Pause behavior spans two layers:

- `MissionManager` changes the lifecycle to `PAUSED` and stops advancement.
- `MissionManagerNode` requests cancellation of active movement commands.

If a command completes while the mission is paused, its successful physical
effect is still applied to the world, but any newly generated follow-up command
is suppressed. Resume returns the mission to `RUNNING` and calls `_advance()`.

### 14.2 Per-robot pause and resume

A robot pause:

- sets `RobotState.paused`
- publishes robot-side pause control
- requests cancellation of that robot's active movement

Other robots may continue because the entire mission is not paused.

### 14.3 Abort

Abort:

- sets the mission to `ABORTED`
- marks unfinished tasks `CANCELLED`
- requests cancellation of active movement commands

Abort does not currently perform explicit resource rollback, robot release, or
package-state reconciliation.

### 14.4 Speed scaling

Speed scaling is handled as infrastructure control rather than a mission task.
The mission node:

1. validates that the scale is between `0.3` and `1.0`
2. stores the requested scale
3. sends a `set_speed_scale` command
4. updates the confirmed scale after a successful robot-side result

## 15. Observability and Read Models

`mission_serializer.py` builds two projections:

```text
mission_state:
  compact dashboard/operator state

mission_debug_state:
  detailed task, command, world, resource, event, and adapter state
```

The compact state exposes:

- mission status and phase
- current and total steps
- current blocker and next step
- package summaries
- robot summaries
- task summaries
- transfer-zone summaries
- active command and blocked-task counts

The debug state additionally exposes:

- all transport tasks
- all execution commands
- complete resource state
- RMF correlation maps
- recent events and actions
- active handling commands

`mission_events` provides append-style event messages. The node only retains the
latest 20 events and actions in memory; this package has no durable event or
audit store.

This is a projection/read-model pattern:

```text
mutable domain state
    |
    v
operator read model + debug read model
```

## 16. End-to-End Package Flow

A normal one-package mission proceeds as follows:

```text
1. Operator starts the mission.
2. Scheduler starts P1:source_to_transfer.
3. tb3_1 moves from robot1_home to source.
4. External handling execution confirms that tb3_1 loaded P1.
5. tb3_1 requests a transfer dropoff lease.
6. If unavailable, tb3_1 moves to or waits at upstream_exit.
7. Once granted, tb3_1 moves to transfer.
8. External handling execution confirms that tb3_1 unloaded P1.
9. P1 is recorded in transfer.package_occupancy.
10. tb3_1 moves to upstream_exit.
11. Transfer robot occupancy and lease are released.
12. The upstream task succeeds.
13. The scheduler starts or resumes P1:transfer_to_destination.
14. tb3_2 requests a transfer pickup lease.
15. If unavailable, tb3_2 moves to or waits at downstream_exit.
16. Once P1 is buffered and transfer is free, tb3_2 enters transfer.
17. External handling execution confirms that tb3_2 loaded P1.
18. P1 is removed from transfer.package_occupancy.
19. tb3_2 moves to downstream_exit.
20. Transfer robot occupancy and lease are released.
21. tb3_2 moves to destination.
22. External handling execution confirms that tb3_2 unloaded P1.
23. The downstream task succeeds.
24. The mission completes when every transport task has succeeded.
```

The current workflow does not return either robot home after mission completion.

## 17. Architectural Characteristics

### 17.1 Centralized orchestration

One mission manager owns the collaboration model. Robots execute commands but
do not independently negotiate the package workflow or transfer ownership.

### 17.2 Event-driven progression

Mission progress occurs when operator or execution events arrive. The core does
not continuously poll robot telemetry.

### 17.3 Hierarchical state

The implementation has three main state machines:

```text
mission lifecycle
task lifecycle and phase
execution-command lifecycle
```

The behavior tree provides ordered workflow progression over those states.

### 17.4 Optimistic world model

Robot and package state are logical assertions based on accepted command
results. Continuous physical reconciliation is outside the current design.

### 17.5 Deterministic execution

Task selection and workflow order are deterministic, which makes the current
lab mission relatively easy to inspect and explain.

## 18. Architectural Strengths

- ROS concerns are separated from the core mission domain.
- Mission decisions are deterministic and explainable.
- World changes follow confirmed execution outcomes.
- Package workflow is decomposed into reusable transport-task instances.
- Transfer coordination distinguishes lease, robot occupancy, and package
  capacity.
- Execution commands have correlation IDs and terminal-state idempotency.
- Verified Nav2 arrival is stronger than RMF lifecycle completion alone.
- Waiting tasks expose operator-facing blocking and recovery information.
- Compact and debug projections are separated.
- Fixed robot roles reduce ambiguity for the current physical experiment.

## 19. Main Limitations

- The entire runtime is in memory; process restart loses mission state.
- Mission topology and robot roles are hard-coded.
- Scheduling is sorted-first rather than optimization-based.
- Resource leases have no queue, timeout, or stale-lease recovery.
- Blocked tasks are retried opportunistically when another event advances the
  mission; there is no explicit resource-event wakeup mechanism.
- Package handling depends on an external result and is not physically verified
  by this package.
- Robot location is a logical waypoint rather than continuous telemetry.
- Mission command context reaches Free Fleet through a side channel.
- RMF request rejection or malformed acceptance does not generate a mission
  failure event and may leave a command without progress.
- Abort does not fully roll back resource, robot, or package state.
- The behavior tree has no native failure or recovery branches.
- There is no persistent event log, replay, or restart reconciliation.
- Mission completion does not return robots home.

## 20. Extension Points

The existing component boundaries provide clear places for future work:

```text
TransportTaskScheduler:
  priorities, fairness, deadlines, robot allocation, cost-based selection

TransportTaskRunner:
  richer workflows, explicit failure branches, recovery, return-home behavior

ResourceManager:
  wait queues, lease timeouts, force release, fairness, stale-state recovery

ExecutionManager:
  durable command IDs, persistence, reconciliation

RmfAdapter:
  explicit rejection events, cancellation support, richer RMF task types

MissionManager:
  explicit dependency graphs, recovery policy, transactional abort behavior

MissionManagerNode:
  physical handling confirmation, richer result validation, persistence hooks

MissionWorld:
  telemetry reconciliation and physical region occupancy
```

## 21. Overall Assessment

The mission layer is a focused orchestration system for a lab-scale,
fixed-role, two-robot handoff. It is substantially cleaner than implementing
the complete workflow as one monolithic ROS callback state machine.

Domain state, scheduling, workflow execution, resource arbitration, external
execution, and read-model publication have distinct responsibilities.

Its main scaling constraints are not the behavior-tree mechanism itself. They
are:

- the optimistic in-memory world model
- the simple scheduling policy
- the lack of durable recovery
- the simple lease model
- fixed mission and robot definitions

For the current two-robot mission, the architecture remains small,
deterministic, and explainable. For larger or safety-critical missions, resource
recovery, persistence, explicit dependency events, and physical-state
reconciliation would need to become first-class parts of the design.
