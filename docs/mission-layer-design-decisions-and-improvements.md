# Mission Layer Design Decisions and Improvement Areas

## 1. Purpose and Scope

This document records the important architectural decisions in the current
mission layer, why they were made, what state the implementation is currently
in, and what would need to change for a more mature system.

The current implementation should be described as:

> A deliberately narrow orchestration prototype for validating a fixed
> two-robot package-handoff mission, with architectural boundaries intended to
> support later evolution.

It is not yet a general-purpose, production-ready mission framework.

The active mission is:

```text
tb3_1                         tb3_2
source --------> transfer --------> destination
       package handoff
```

The mission layer owns collaboration and workflow semantics. Open-RMF and Nav2
own traffic-aware navigation and robot-local movement.

## 2. Architectural Setup

The system is a centralized, event-driven orchestrator with a layered
organization:

```text
ROS integration layer
  MissionManagerNode
  RmfAdapter

Application orchestration layer
  MissionManager
  TransportTaskScheduler
  TransportTaskRunner

Domain and state layer
  MissionRuntime
  MissionWorld
  TransportItemTask
  ResourceState
  ExecutionCommand

Execution layer
  Open-RMF
  Free Fleet
  Nav2
  external package-handling executor
```

The central runtime loop is:

```text
Event arrives
    ↓
MissionManager updates state
    ↓
Scheduler and behavior tree determine the next work
    ↓
ExecutionCommand is emitted
    ↓
External system performs the work
    ↓
Execution result becomes another event
    └──────────────── repeat
```

This resembles ports-and-adapters architecture because the domain decides what
should happen while ROS and RMF adapters arrange for it to happen. It is not a
strict hexagonal implementation because most boundaries use concrete classes
rather than formal port interfaces.

## 3. Decision Summary

| Decision | Reason | Current state | Main improvement |
|---|---|---|---|
| Centralized mission manager | Reduce coordination complexity | One in-memory authority | Persistence, failover, ownership |
| Fixed robot roles | Match the physical experiment | Robot IDs hard-coded | Capability-based allocation |
| Two tasks per package | Make handoff legs explicit | Dependency implicit in package state | Explicit task dependency graph |
| Event-driven progression | External execution is asynchronous | Progress driven by result events | Timeouts and reconciliation |
| Memory-sequence behavior tree | Express resumable workflow | Minimal `SUCCESS`/`RUNNING` BT | Failure and recovery branches |
| Separate scheduler and task runner | Separate task selection from execution | Deterministic sorted-first scheduler | Priority, cost, and fairness |
| Mission-owned belief state | RMF does not own package semantics | Logical in-memory world | Sensor reconciliation and persistence |
| Command/result boundary | Keep execution outside the domain | Move and handling commands | Durable IDs and deduplication |
| Lease-based transfer resource | Enforce shared-zone constraints | One lease, capacities of one | Queues, expiry, fencing, recovery |
| Verified Nav2 arrival | Avoid advancing from weak RMF lifecycle signals | Position-based arrival validation | Formal execution correlation |
| Read-model serialization | Separate runtime state from UI shape | Compact and debug projections | Versioned schemas and persistence |

## 4. Centralized Orchestration

### Decision

One `MissionManager` owns:

- mission lifecycle
- task lifecycle
- package workflow
- logical robot assignments
- transfer access
- command progression

Robots do not negotiate directly with one another.

### Justification

Centralization was appropriate for the current scope because it provides:

- one authoritative mission state
- deterministic decisions
- simpler debugging
- straightforward transfer arbitration
- lower coordination complexity for two robots

### Current state

The runtime exists entirely in one process. `MissionManagerNode` creates one
`MissionManager`, which contains one `MissionRuntime`.

### Limitations

- The node is a single point of failure.
- Restart constructs a fresh mission.
- There is no multi-instance mission ownership.
- There is no leader election or failover.
- There is no distributed consistency protocol.

### Improvement direction

The first improvement should be durable state and restart reconciliation, not
immediate distribution. Only introduce multiple mission-manager instances when
availability or scale requirements justify the additional complexity.

## 5. Fixed Mission and Robot Roles

### Decision

The mission definition fixes:

```text
tb3_1: source to transfer
tb3_2: transfer to destination
```

Waypoints and the fleet name are also defined in source code.

### Justification

- Directly matches the lab experiment.
- Removes dynamic allocation uncertainty.
- Makes behavior deterministic.
- Allows the transfer protocol to be validated independently of scheduling
  optimization.

### Current state

Each package creates:

```text
P1:source_to_transfer       assigned to tb3_1
P1:transfer_to_destination  assigned to tb3_2
```

### Limitations

- Robots cannot substitute for one another.
- A failed robot makes its assigned workflow unavailable.
- Mission topology changes require code changes.
- The task model assumes one robot, one pickup, and one dropoff.

### Improvement direction

- Define required robot capabilities instead of fixed IDs.
- Move mission topology into validated configuration.
- Let the scheduler allocate eligible robots.
- Preserve optional fixed assignments for controlled experiments.

## 6. Task Decomposition and Dependencies

### Decision

One package delivery is decomposed into two `TransportItemTask` instances rather
than represented as one large mission state machine.

### Justification

- Each robot receives a clear unit of work.
- Upstream and downstream legs have independent states.
- The handoff is visible and inspectable.
- The two legs can overlap through pre-staging.
- The same task workflow can be reused for both legs.

### Current dependency model

There is no explicit dependency such as:

```text
downstream_task depends_on upstream_task
```

Instead, dependency is represented implicitly through state:

```text
upstream unload succeeds
    ↓
package enters transfer.package_occupancy
    ↓
downstream pickup access becomes possible
```

### Limitations

- Dependencies are difficult to inspect generically.
- More complex task graphs would require additional special cases.
- Package state and resource state perform double duty as workflow dependency
  signals.

### Improvement direction

Introduce explicit task dependencies or preconditions:

```text
Task B requires:
  package P1 buffered at transfer
  transfer pickup lease available
```

Keep resource checks authoritative even if an explicit dependency graph is
added.

## 7. Event-Driven Progression

### Decision

The mission progresses in response to events rather than continuously polling
robot state.

Important events include:

- mission start
- pause, resume, and abort
- command completion
- command failure
- command cancellation

### Justification

- Robot operations are asynchronous.
- ROS callbacks should not block while robots move.
- Every transition can be associated with a concrete outcome.
- Command/result flows are easy to inspect.

### Current state

`MissionManager.handle_event()` updates state and calls `_advance()`.
`_advance()` ticks active tasks and may schedule new work.

### Limitations

- A lost result can leave a command active indefinitely.
- There is no general command timeout.
- Resource changes do not produce formal domain wakeup events.
- Blocked tasks are retried opportunistically when another event calls
  `_advance()`.
- There is no restart reconciliation.

### Improvement direction

Add explicit events:

```text
PackageBuffered
PackageRemoved
ResourceLeaseReleased
RobotClearedResource
CommandTimedOut
WorldStateReconciled
```

A low-frequency reconciliation watchdog can detect missing events, but normal
progression should remain event-driven.

## 8. Scheduler and Task Runner Separation

### Decision

Scheduling and task execution are separate:

```text
Scheduler:
  Which pending task may start?

Behavior-tree runner:
  What should a running task do next?
```

### Justification

Scheduling policy and workflow policy change for different reasons. Separating
them avoids mixing fleet-level selection with step-level execution.

### Current scheduler

The scheduler sorts task IDs and selects the first pending task for which:

- an assigned robot exists
- the robot is idle and not paused
- the package is available, or pre-staging is allowed
- the managed pickup resource is available

### Current concurrency

Each robot can own one task, so the system permits limited overlap:

```text
tb3_1 carries P1 toward transfer
tb3_2 waits at downstream_exit
```

### Limitations

- No priorities or deadlines.
- No cost model.
- No fairness beyond task-ID ordering.
- No dynamic robot allocation.
- Lexical task-ID order is an implementation detail, not a scheduling policy.

### Improvement direction

Add policy only when requirements exist:

- explicit priority
- age/fairness
- deadlines
- robot capabilities
- travel cost
- resource contention cost

## 9. Behavior-Tree Workflow

### Decision

Each transport task uses a memory-sequence behavior tree:

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

### Justification

- The workflow is sequential and naturally decomposes into steps.
- A memory sequence resumes after asynchronous operations.
- Nodes encapsulate resource, movement, and handling behavior.
- It is easier to evolve than one monolithic callback FSM.

### Current state

The custom BT supports only:

```text
SUCCESS
RUNNING
```

Failures are handled by `MissionManager`, not propagated through the tree.

### Limitations

- No BT-level failure status.
- No fallback/selectors.
- No retry decorators.
- No explicit recovery subtrees.
- Tree structure is fixed in Python.
- For the current workflow, it behaves similarly to a structured hierarchical
  state machine.

### Improvement direction

Do not replace it merely for architectural fashion. Extend it when recovery
requirements exist:

- explicit failure results
- retry/recovery nodes
- fallback branches
- reusable subtrees
- task-specific trees

## 10. Task, Action, Command, and Event Model

The following concepts must remain distinct:

| Concept | Meaning | Example |
|---|---|---|
| Mission task | Complete logical work unit | Move P1 from source to transfer |
| BT node | One workflow step | Move to pickup |
| Execution command | Request for external work | `MOVE_ROBOT cmd_1` |
| RMF task | RMF representation of movement | Composed `go_to_place` task |
| Event | Observed request or outcome | `ExecutionCommandCompleted` |

### Internal actions

Performed synchronously in mission state:

- assign robot
- create lease
- mark resource occupied
- buffer package
- release resource
- mark task succeeded

### External actions

Require another system:

- move robot
- load or unload package
- cancel movement
- pause or resume robot
- change robot speed

The core models move and handling work as `ExecutionCommand` objects.

### Command invariant

A task normally has at most one active external command:

```text
active_command_id is None:
  a command may be emitted

active_command_id exists:
  the task remains RUNNING
```

### Current limitations

- Command IDs reset on process restart.
- Robot-side exactly-once execution is not guaranteed.
- Lost results are not generally recovered.
- Retrying non-idempotent handling can be unsafe.

### Improvement direction

- Use durable globally unique command IDs.
- Persist command lifecycle.
- Deduplicate commands robot-side.
- Reconcile physical state before retrying handling.
- Define timeout and compensation policies.

## 11. Mission-Owned Belief State

### Decision

`MissionWorld` contains the mission layer's logical understanding of:

- robot locations and assignments
- package location and carrier
- transfer lease and occupancy

### Justification

RMF does not own package or handoff semantics. The mission needs this state to
make task and resource decisions.

### Current state

The world is updated after accepted execution results:

```text
verified movement:
  update logical robot waypoint

successful load:
  assign package carrier

successful unload:
  update package location
```

### Important qualification

`MissionWorld` is a belief model, not guaranteed physical truth.

### Limitations

- No persistence.
- No continuous telemetry reconciliation.
- Package handling success is externally reported rather than physically
  verified by this package.
- Transfer clearance is inferred from reaching an exit waypoint.
- Stale logical state may persist after failures.

### Improvement direction

- Record observation source and timestamp.
- Reconcile against robot pose and package sensors.
- Persist snapshots or transitions.
- Define confidence and stale-state behavior.
- Require operator confirmation when physical state is ambiguous.

## 12. Collaboration and Constraint Enforcement

Collaboration is mediated through shared state, not direct robot messages:

```text
tb3_1 unload result
    ↓
package and transfer state change
    ↓
blocked downstream task becomes eligible
    ↓
tb3_2 receives its next command
```

### Constraint layers

| Constraint | Enforcement point |
|---|---|
| Fixed robot role | Mission construction |
| Task readiness | Scheduler |
| Workflow ordering | Memory-sequence BT |
| One active task per robot | Robot assignment state |
| One active command per task | `active_command_id` |
| Transfer access | Resource manager lease |
| Transfer robot capacity | `robot_occupancy` |
| Transfer package capacity | `package_occupancy` |
| Valid package pickup | Package presence check |
| Verified movement completion | Mission node result validation |
| Traffic and route conflicts | RMF graph, mutexes, and Nav2 |

### Core logical invariants

The design attempts to maintain:

```text
One robot owns at most one active mission task.
One task has at most one active external command.
Only one robot may lease transfer.
Only one robot may occupy transfer.
Only one package may be buffered at transfer.
A transfer pickup requires the requested package to be buffered.
A task succeeds only after every workflow step succeeds.
The mission completes only after every task succeeds.
Logical robot location changes only after verified movement.
```

These are in-process logical invariants, not database constraints or physical
safety interlocks.

## 13. Transfer Resource Protocol

### Decision

Transfer separates:

```text
active_lease:
  permission and intent

robot_occupancy:
  robot logically inside the resource

package_occupancy:
  package buffered at the resource
```

### Dropoff access requires

- no conflicting lease
- robot capacity available
- package capacity available
- a package ID

### Pickup access requires

- no conflicting lease
- robot capacity available
- requested package buffered

### Waiting behavior

Unavailable access produces:

```text
WAIT:
  move to upstream_exit or downstream_exit

BLOCKED:
  stop without a safe movement target
```

The task also records an operator-facing reason, unblock condition, and expected
next event.

### Release protocol

The lease is held while the robot:

1. approaches transfer
2. enters transfer
3. handles the package
4. exits to its directional clear point

Only after reaching the exit are occupancy and lease released.

### Limitations

- One lease only.
- No queue or fairness.
- No expiry or heartbeat.
- No fencing token.
- No operator force-release.
- No independent region-clear sensor.

### Improvement direction

- Add queued requests and fairness.
- Add lease expiry and renewal.
- Add ownership/fencing version.
- Add operator recovery.
- Reconcile logical occupancy with physical region detection.

## 14. Verified Movement Completion

### Decision

RMF task completion does not directly advance the mission. Movement success must
come from the Free Fleet/Nav2 result path with:

```text
expected result source
arrival_verified = true
```

### Justification

RMF lifecycle completion does not provide enough final-pose evidence to safely
begin package handling.

### Current state

The Free Fleet adapter correlates mission command context with navigation,
calculates final distance to the target, and publishes the result. Failed
arrival verification is retried a limited number of times.

### Limitations

- Command context is passed through a side channel.
- Correlation depends partly on matching navigation targets.
- Position verification may not prove handling alignment or orientation.
- RMF request rejection is not fully converted into mission failure.

### Improvement direction

- Define a formal execution interface carrying command identity end to end.
- Add request-acceptance timeout and rejection events.
- Validate orientation or docking state where handling requires it.

## 15. Pause, Abort, and Failure Semantics

### Current pause behavior

- Mission pause stops mission advancement.
- The ROS node requests cancellation of active moves.
- Successful effects received during pause are applied.
- Follow-up commands are suppressed until resume.

### Current robot pause behavior

- One robot is marked paused.
- Robot-side pause control is published.
- That robot's active move is cancelled.
- Other robots may continue.

### Current abort behavior

- Mission becomes `ABORTED`.
- Unfinished tasks become `CANCELLED`.
- Active moves are requested to cancel.

### Limitations

- Abort does not transactionally release all leases and robot ownership.
- Physical package state is not reconciled.
- Lost cancellation results can leave ambiguous state.
- There is no compensation workflow.
- There is no resume-from-failure policy.

### Improvement direction

Define explicit recovery states and operator procedures:

```text
CANCELLING
RECOVERING
RECONCILING
REQUIRES_OPERATOR
```

Abort should be treated as a workflow, not merely a status change.

## 16. Idempotency and Delivery Semantics

`ExecutionManager` ignores duplicate terminal transitions, so repeated
completion messages do not normally advance a command twice.

This is not exactly-once physical execution.

Example ambiguity:

```text
Robot loads package successfully.
Success result is lost.
Mission still believes the command is running.
Retrying could repeat a physical operation.
```

A mature system needs:

- stable command identity
- robot-side deduplication
- idempotent operations where possible
- physical observation before retry
- explicit at-least-once delivery assumptions

## 17. Safety Boundary

The mission resource model is a coordination mechanism, not a certified safety
system.

It assumes:

- waypoint arrival represents entry and clearance
- execution results are trustworthy
- localization is sufficiently accurate
- RMF graph and mutex configuration match mission semantics
- Nav2 performs local collision avoidance

Production safety could require:

- physical geofence or region occupancy
- safety-rated sensing and controls
- conservative behavior under communication loss
- independent emergency-stop integration
- lease fencing and fail-safe expiry

## 18. Observability and Read Models

The mission layer publishes:

```text
mission_state:
  compact operator projection

mission_debug_state:
  detailed domain and adapter state

mission_events:
  append-style event messages
```

### Current strengths

- Operators can see blockers and expected recovery conditions.
- UI shape is separated from raw runtime objects.
- Debug state exposes tasks, commands, resources, and correlations.

### Current limitations

- Events are retained only in memory.
- There is no durable audit history.
- Event IDs and command IDs are not restart-stable.
- Schema compatibility is not strongly managed.

### Improvement direction

- Version published schemas.
- Persist mission transitions and command history.
- Add correlation and causation IDs.
- Provide metrics for command latency, blocking time, retries, and lease age.

## 19. Maturity Assessment

### Sound foundations to retain

- Separation between mission policy and ROS transport.
- Separate scheduling and task execution.
- Command/result execution boundary.
- Explicit resource model.
- Separation of lease, robot occupancy, and package occupancy.
- State updates after confirmed outcomes.
- Verified Nav2 arrival.
- Operator-visible blocker information.
- Separate compact and debug projections.

### Intentional scope decisions

- Two robots.
- Fixed roles.
- One transfer resource.
- One active mission.
- In-memory state.
- Deterministic scheduler.
- Minimal behavior tree.

### Architectural gaps

- Persistence and restart recovery.
- Dynamic robot allocation.
- Explicit task dependencies.
- Timeouts and reconciliation.
- Physical package verification.
- General mission definition.
- Strong abort and failure recovery.
- Durable command identity and deduplication.
- Resource queues, expiry, and fencing.
- Multi-mission ownership and scaling.

## 20. Recommended Improvement Roadmap

### Stage 1: Strengthen the fixed scenario

- Add command and lease timeouts.
- Convert RMF rejection into mission failure.
- Add explicit resource-change events.
- Add operator state correction and force-release.
- Reconcile resources during abort.
- Persist mission snapshots and command correlations.
- Improve physical package confirmation.

### Stage 2: Generalize configuration

- Move roles, waypoints, and resources into validated configuration.
- Add explicit task preconditions and dependencies.
- Allocate robots by capability.
- Add scheduling priority and fairness.

### Stage 3: Add durable recovery

- Use globally unique command IDs.
- Persist events or state transitions.
- Reconcile RMF, robot, package, and resource state after restart.
- Add robot-side command deduplication.
- Define compensation policies.

### Stage 4: Scale when required

- Support multiple missions.
- Define durable mission ownership.
- Introduce leader election or workflow partitioning.
- Separate command workers and read projections if operational scale requires
  it.

## 21. Overall Position

The system is optimized for clarity and validation of one physical
collaboration scenario. It establishes useful boundaries between mission
policy, shared-resource coordination, and robot execution.

Its main constraints are not the use of a behavior tree. They are the
optimistic in-memory world model, fixed mission configuration, simple resource
policy, and limited recovery semantics.

The correct evolution strategy is to retain the existing responsibility
boundaries while strengthening persistence, correlation, reconciliation,
physical verification, and configuration.
