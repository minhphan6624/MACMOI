# Mission Layer Refactor Plan

This document records the architectural reason for moving beyond the current v1
mission manager and the intended component split for the next mission-layer
refactor.

The next refactor should not only polish the existing fixed FSM shape. It should
introduce the first generalized mission-task and resource boundaries while
preserving the current two-robot handoff as the default behavior.

It sits beside the existing mission documents:

* `mission_layer_progress.md` remains the current implementation reference.
* `mission_layer_extension_roadmap.md` remains the broader extension roadmap.
* This document focuses on why the current implementation needs refactoring and
  what responsibilities the next architecture should separate.

---

## 1. Current Implementation

The current mission manager is a ROS-wrapped, event-driven, rule-evaluated
mission FSM for a fixed two-robot package handoff.

The implemented mission is intentionally narrow:

```text
source -> transfer -> destination

upstream robot: source -> transfer
downstream robot: transfer -> destination
```

The current runtime flow is:

```text
RMF task/fleet updates
  -> RmfMissionBridge
  -> mission events
  -> MissionManager
  -> rule_evaluator
  -> mission actions
  -> MissionManagerNode
  -> RMF task API / timers / mission_state
```

Current assumptions:

* fixed upstream and downstream robot roles
* one transfer zone
* one package buffer at the transfer zone
* one shared staging waypoint near the transfer zone
* RMF patrol-style waypoint tasks instead of native RMF delivery tasks
* one mission state is created when the ROS node starts

The current mission can be reinterpreted as two concrete instances of a more
general transport task:

```text
transportItem(P1, source, transfer, robot_id=tb3_1)
transportItem(P1, transfer, destination, robot_id=tb3_2)
```

This generalized view should guide the refactor even if the first implementation
still executes the same fixed route.

This design is appropriate for the first implementation because it proves the
package handoff behavior, RMF task API integration, mission-state publication,
and web/API observation path.

---

## 2. Current Component Responsibilities

The current package is split into a small mission core, an RMF bridge, and a ROS
runtime shell.

`MissionManager`

* owns `MissionState`
* receives mission events
* mutates mission, package, robot, and transfer state
* emits mission actions after each event
* records accepted RMF task IDs back onto mission state

`rule_evaluator`

* contains deterministic dispatch policy
* checks mission completion
* starts the next upstream package when allowed
* stages or dispatches the downstream robot
* grants transfer entry when staging conditions clear

`TransferController`

* acts as the first small transfer-zone resource controller
* tracks transfer robot occupancy
* tracks the package buffer
* records a waiting upstream robot/package pair
* answers whether upstream or downstream robot may enter the transfer zone

`RmfMissionBridge`

* translates mission actions into RMF `robot_task_request` payloads
* maps mission task segments to concrete RMF waypoints
* tracks pending RMF API request IDs
* tracks accepted RMF task IDs with mission context
* translates RMF task completions back into mission events

`MissionManagerNode`

* owns ROS publishers and subscribers
* publishes RMF task API requests
* subscribes to RMF task responses, task summaries, and fleet states
* runs handling timers for load/unload delays
* publishes serialized mission state
* keeps recent event/action debug history
* receives simple mission command JSON

API/UI

* observes the `mission_state` ROS topic through the API server
* exposes current mission state to the dashboard
* sends limited mission commands, currently mainly `start`

---

## 3. Why Refactor Is Needed

The current FSM is implicit. There is no single explicit state that says exactly
what the mission is doing. Instead, behavior depends on combinations of:

* mission status
* package status
* robot status
* robot logical location
* transfer-zone state
* active package IDs
* active RMF task IDs

That is workable for the fixed v1 workflow, but it becomes hard to reason about
as soon as the system becomes more dynamic.

The current `MissionManager` and `rule_evaluator` also mix several concerns:

* mission lifecycle
* package flow
* robot role behavior
* transfer resource policy
* dispatch timing
* completion handling
* robot positioning decisions

`RmfMissionBridge` also carries mission meaning through `TaskSegment`. For
example, a completed RMF task is interpreted differently depending on whether
the segment was `SOURCE_TO_TRANSFER`, `STAGING_TO_TRANSFER`, or
`TRANSFER_TO_DESTINATION`. This is useful for v1, but it means the bridge is
still partly mission-aware instead of being only an execution adapter.

The current design is therefore weak for future requirements such as:

* more than two robots
* flexible robot assignment
* configurable mission task types such as `transportItem`
* multiple transfer zones or buffers
* configurable resources and capacities
* resource contention across missions
* retries and recovery behavior
* failures and partial cancellation
* planner-generated routes
* task allocation and prioritization
* formal concurrency/resource analysis

The refactor should preserve what works while separating responsibilities so the
mission layer can grow without turning into a larger implicit FSM.

The important design choice is to build a general shape, not a general planner:
generalized task/resource interfaces should be introduced early, while planners,
task allocators, and formal concurrency engines should remain later extensions.

---

## 4. Target Architecture

The target architecture should split mission ownership, scheduling, execution,
world/resource state, and RMF integration.

Forward execution flow:

```text
Mission Orchestrator
  -> Scheduler / Dispatcher
  -> BT Executor
  -> Execution Adapter / RMF Adapter
  -> RMF / Robots
```

Feedback flow:

```text
RMF / Robots
  -> Execution Adapter
  -> World / Resource Manager
  -> Scheduler / BT Executor
  -> Mission Orchestrator
  -> Mission API / UI
```

The target domain model should include generalized mission tasks and resources:

```text
Task type:
  transportItem(item_id, pickup, dropoff, robot_id?)

Task instance:
  transportItem(P1, source, transfer, robot_id=tb3_1)

Resource:
  id, type, capacity, occupancy, reservations
```

The current mission's hardcoded assumptions should become the default mission
profile:

```text
resource transfer:
  robot_capacity = 1
  package_capacity = 1

role upstream:
  eligible_robots = [tb3_1]

role downstream:
  eligible_robots = [tb3_2]
```

### Mission Orchestrator

The Mission Orchestrator owns mission-level lifecycle and operator-facing state.

Responsibilities:

* load or create mission task instances
* submit mission
* start mission
* pause mission
* resume mission
* abort mission
* reset or clear terminal mission
* track high-level mission status
* expose mission summaries to API/UI
* start or stop execution units through the scheduler

It should coordinate the mission, not directly encode every robot movement and
resource rule.

### World / Resource Manager

The World/Resource Manager owns the operational truth used by schedulers and
executors.

Responsibilities:

* configurable resource definitions
* robot logical state
* package location/state
* transfer-zone state
* staging-zone state
* buffer state
* resource occupancy
* resource reservations
* resource acquisition/release rules
* resource capacity validation
* world updates derived from RMF or robot feedback

The current `TransferController` is the seed of this component, but it only
models one transfer zone and one package buffer.

### Scheduler / Dispatcher

The Scheduler decides what mission task should advance next.

Responsibilities:

* choose which task instance should run
* start execution units
* avoid oversubscribing resources
* handle simple priority decisions
* later integrate task allocation or planning

The first scheduler can keep the current deterministic rules internally:
packages are processed in order, `tb3_1` handles source-to-transfer work, and
`tb3_2` handles transfer-to-destination work. The important change is the
boundary: scheduling decisions should operate over task/resource concepts and no
longer be hidden inside the mission manager.

### BT Executor

The BT Executor executes mission-level task workflows.

Responsibilities:

* run task behavior trees
* execute generalized task workflows such as `transportItem`
* sequence robot actions
* wait for conditions
* retry or fail task steps
* emit execution status
* request resource operations through the World/Resource Manager
* request robot execution through the RMF adapter

BTs are a good fit for workflows that contain navigation, loading, waiting,
resource acquisition, fallback paths, and recovery.

### RMF Adapter

The RMF Adapter should be a protocol/execution adapter.

Responsibilities:

* convert execution commands into RMF task API requests
* track RMF request IDs and task IDs
* convert RMF task updates into execution/world events
* hide RMF JSON/message details from mission logic

Over time, it should move away from interpreting mission-specific segments and
toward reporting generic command lifecycle events such as submitted, completed,
failed, or cancelled.

---

## 5. BT Executor Clarification

BTs should manage mission-task execution, not global scheduling.

Valid BT scopes include:

```text
transportItem(P1, source, transfer, tb3_1)
transportItem(P1, transfer, destination, tb3_2)
UpstreamDelivery(P1)    # fixed-mission specialization of transportItem
DownstreamDelivery(P1)  # fixed-mission specialization of transportItem
```

For the current fixed mission, an upstream delivery tree could look like:

```text
transportItem(P1, source, transfer, tb3_1)
  Sequence
    NavigateToPickup
    LoadItem
    AcquireTransferOrGoToStaging
    NavigateToDropoff
    UnloadItem
    ReleaseTransfer
```

The responsibility split should remain:

```text
Scheduler:
  decides which BT should run

BT Executor:
  executes the selected workflow

World / Resource Manager:
  validates resource state and records resource ownership

RMF Adapter:
  executes robot navigation/movement through RMF
```

The BT should not become the global coordinator for package ordering, robot
allocation, mission priority, or resource arbitration across the entire system.

---

## 6. Refactor Steps

### Step 1: Preserve Current Behavior And Invariants

Document current invariants and keep the fixed two-robot mission as the
regression baseline.

Examples:

* only one robot occupies transfer
* only one package is buffered at transfer
* a paused mission does not dispatch new work
* a completed package is not dispatched again
* duplicate RMF task completion does not advance state twice

### Step 2: Define Generalized Task And Resource Models

Introduce the minimal domain concepts needed for the target architecture:

```text
TransportItem task instance:
  task_id
  item_id
  pickup
  dropoff
  robot_id
  status

Resource:
  resource_id
  type
  robot_capacity
  package_capacity
  occupancy
  reservations
```

The current mission should be encoded as default task instances and default
resource settings, not as new hardcoded behavior.

### Step 3: Create The New Runtime Core

Create the new in-process runtime modules without switching the ROS node first:

```text
MissionOrchestrator
RuntimeWorld
TransportTaskScheduler
ExecutionManager
```

The core should create default `transportItem` tasks, own robot/item/resource
state, select ready tasks, and emit execution commands.

### Step 4: Replace Rule Flow With Task Flow

Drive the current mission through task instances instead of the old
`MissionManager -> rule_evaluator` path.

The first task flow should run:

```text
transportItem(P1, source, transfer, tb3_1)
transportItem(P1, transfer, destination, tb3_2)
```

using explicit task workflow steps:

```text
acquire pickup/dropoff resource when needed
move robot
load item
unload item
release resource
mark task succeeded
```

### Step 5: Extract World / Resource Manager

Move transfer-zone ownership and transfer-related rule logic out of the current
mission/rule path into a dedicated World/Resource Manager.

The first version can still support only the existing single transfer zone. The
goal is to establish the boundary before adding multiple resources.

### Step 6: Introduce A Scheduler Interface

Use a Scheduler/Dispatcher interface that works over task instances and resource
state.

The first implementation should keep the current deterministic dispatch rules.
The architectural change is that future task allocation, priorities, and
planner output have a clear place to plug in.

### Step 7: Introduce Execution Command IDs

Move toward generic execution command lifecycle tracking.

Instead of relying on mission-specific `TaskSegment` meaning inside the RMF
bridge, execution commands should have stable IDs that can be submitted,
accepted, completed, failed, or cancelled.

### Step 8: Add A Lightweight Execution Layer

Add a small execution layer that tracks command lifecycle and owns the mapping
between task workflow steps and execution commands.

This layer becomes the bridge between scheduler/BT intent and RMF adapter
execution.

### Step 9: Switch The ROS Node To The New Core

Replace the runtime use of the old `MissionManager` with the new orchestrator,
execution manager, scheduler, and world model. Mission commands should start or
control the orchestrator, and RMF/timer completions should complete execution
commands.

### Step 10: Add BT Execution For One Workflow

Introduce BT execution for one `transportItem` workflow only after the
world/resource, scheduler, and execution-command boundaries are stable.

The first BT should preserve the existing behavior rather than add new mission
capability.

### Step 11: Remove Legacy Mission Controller Code

After the ROS node runs through the new task flow, remove the old
`MissionManager`, `rule_evaluator`, and `TransferController` path.

### Step 12: Add Advanced Coordination Only When Needed

Add planners, task allocators, or Petri net coordination only when the system has
enough resource contention and concurrency to justify them.

These should extend the Scheduler or World/Resource Manager boundary instead of
replacing the whole mission architecture.

---

## 7. Design Defaults

Use these defaults for the first refactor phase:

* keep the current ROS topics initially
* keep the current dashboard mission-state shape initially
* keep mission logic testable without ROS
* keep the existing two-robot fixed mission behavior as the regression baseline
* encode the current transfer-zone constraints as default resource capacities
* encode the current upstream/downstream routes as default `transportItem` task instances
* keep robot assignment deterministic in the first scheduler
* do not introduce a planner in the first refactor step
* do not introduce Petri net coordination in the first refactor step
* do not introduce a full BT framework before the component boundaries are clear
* keep RMF as the robot execution and traffic coordination layer

---

## 8. Validation Scenarios

These scenarios should remain true during the refactor:

* one-package mission completes end to end
* upstream robot stages when transfer is blocked
* downstream robot picks up only when the transfer buffer has a package
* mission does not dispatch new work while paused
* duplicate RMF task completion does not double-advance mission state
* mission state JSON remains usable by the current API/UI
* RMF task requests are still generated for the current fixed waypoint flow

The initial refactor should be judged by behavioral preservation and clearer
ownership boundaries, not by adding new mission capability.
