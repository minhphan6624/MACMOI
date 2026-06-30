# Mission Layer Presentation Questions and Justifications

## 1. Recommended Presentation Position

Do not present the system as a mature general-purpose mission platform.

Use this framing:

> The current mission layer is a centralized orchestration prototype built to
> validate a fixed two-robot package handoff. It deliberately prioritizes
> deterministic behavior, explainability, and clear integration boundaries over
> dynamic allocation, distributed operation, and complete failure recovery.

This separates:

```text
intentional scope decisions
sound architectural foundations
known maturity gaps
```

## 2. One-Sentence Description

> The mission layer converts high-level multi-robot collaboration rules into an
> event-driven sequence of externally executed robot commands while maintaining
> the logical state of robots, packages, tasks, and shared resources.

## 3. What Problem Does the Mission Layer Solve?

### Question

Why is a mission layer required?

### Answer

RMF and Nav2 understand navigation and traffic, but they do not inherently
understand this application workflow:

- one package has two transport legs
- two specific robots perform different roles
- the downstream leg depends on a package handoff
- transfer has both robot and package capacity
- package handling requires confirmation
- operators need mission-level progress and blocker information

The mission layer owns those application semantics.

## 4. Why Not Let RMF Handle Everything?

RMF is used as the traffic-aware movement execution substrate. The mission layer
adds domain rules that RMF does not own:

```text
package custody
handoff readiness
transfer package capacity
load/unload confirmation
cross-robot task dependency
operator recovery context
```

RMF decides how a robot reaches a waypoint safely within the fleet traffic
model. The mission layer decides whether that movement is currently valid for
the package workflow.

## 5. Why Not Represent the Whole Mission as One RMF Task?

The workflow includes state outside navigation:

- two robots
- package ownership changes
- transfer leases
- handling operations
- conditional waiting
- cross-task dependencies
- operator pause and recovery

Representing everything as one opaque RMF task would hide these states and make
mission-level control and observability more difficult.

## 6. What Kind of Architecture Is This?

It is primarily:

```text
centralized
event-driven
layered
command/result based
```

It also resembles ports-and-adapters architecture:

- domain code decides what should happen
- ROS/RMF adapters execute or transmit that decision
- external outcomes return as events

It is not full event sourcing, CQRS, or a distributed workflow engine.

## 7. Is This Event Sourcing?

No.

The system uses events for progression and observability, but:

- state is mutated directly
- events are not durably persisted
- runtime state cannot be rebuilt by replaying events
- there is no event store

The accurate term is event-driven orchestration with command/result separation.

## 8. Why Is the Mission Manager Centralized?

### Justification

- Only two robots and one constrained resource are involved.
- One authority makes transfer arbitration deterministic.
- It reduces distributed coordination complexity.
- It is easier to inspect during physical experiments.

### Tradeoff

- Single point of failure.
- No failover.
- No multi-instance ownership.
- Restart loses mission state.

### Future direction

Add persistence and reconciliation before attempting distributed orchestration.

## 9. How Is the Mission Created?

At startup, `MissionManagerNode` reads:

```text
mission_id
total_packages
auto_start
```

`MissionManager.create_default()` then creates:

```text
two transport tasks per package
one PackageState per package
two RobotState objects
one transfer ResourceState
one MissionWorld
one MissionRuntime
one MissionManager
```

The manager creates its default scheduler, execution manager, and transport
behavior-tree runner.

## 10. Why Are Robot Roles Fixed?

### Justification

Fixed roles match the physical experiment and isolate the handoff problem from
robot allocation.

### Current limitation

The system cannot replace a failed robot or choose a better robot dynamically.

### Improvement

Describe tasks using required capabilities, then let the scheduler allocate an
eligible robot. Fixed assignment can remain an optional policy.

## 11. How Are Tasks Modeled?

One `TransportItemTask` represents:

```text
move item X
from pickup A
to dropoff B
using robot R
```

It stores:

- task definition
- lifecycle status
- workflow phase
- active external command
- resource-wait state
- blocker details
- behavior-tree position

One package creates two task instances:

```text
P1:source_to_transfer
P1:transfer_to_destination
```

## 12. Why Split One Delivery Into Two Tasks?

The split:

- gives each robot a clear responsibility
- exposes the transfer handoff
- allows each leg to wait or fail independently
- permits downstream pre-staging
- avoids one large mission-specific state machine

The weakness is that the dependency between the tasks is implicit in package
and transfer state rather than represented as an explicit task edge.

## 13. How Is Task Dependency Represented?

Currently:

```text
upstream unloads P1
    ↓
P1 enters transfer.package_occupancy
    ↓
downstream pickup becomes valid
```

There is no explicit `depends_on` field.

This works for the fixed workflow. A more general mission framework should
represent task dependencies and preconditions explicitly while retaining
resource checks as enforcement.

## 14. What Is the Difference Between a Task and an Action?

Use this terminology:

| Term | Meaning |
|---|---|
| Mission task | Complete package leg |
| BT node | One logical workflow step |
| Execution command | One request for external work |
| RMF task | RMF navigation execution |
| Event | A request or observed outcome |

Example:

```text
Mission task:
  P1:source_to_transfer

BT node:
  MoveTo(source)

Execution command:
  cmd_1 MOVE_ROBOT tb3_1 source

RMF task:
  composed go_to_place request

Event:
  ExecutionCommandCompleted(cmd_1)
```

## 15. Why Use a Behavior Tree?

The task workflow is sequential but contains asynchronous movement, handling,
and resource waits.

A memory sequence:

- expresses the workflow as composable steps
- stops when an external command is running
- stores the unfinished position
- resumes after the result event

The current implementation is minimal and behaves similarly to a structured
hierarchical state machine. It does not yet use advanced BT features such as
fallbacks, decorators, or recovery subtrees.

## 16. Could a Finite-State Machine Be Used Instead?

Yes.

For this fixed sequence, a hierarchical FSM would also be reasonable. The BT
was chosen for readable sequential composition and potential future reuse of
nodes and subtrees.

The argument should not be that behavior trees are always better. The current
benefit is structured resumability and future composability.

## 17. What Is the Difference Between the Scheduler and the BT?

```text
Scheduler:
  decides which pending task may begin

Behavior tree:
  decides what a running task should do next
```

Keeping these separate allows scheduling policy to evolve without rewriting the
transport workflow.

## 18. How Does the Scheduler Work?

It sorts task IDs and selects the first task where:

- status is `PENDING`
- the assigned robot is idle and not paused
- the package is available, or pre-staging is valid
- managed pickup constraints allow progress

It is deterministic but not optimized.

It currently has no:

- priority
- deadline
- cost model
- fairness policy
- dynamic robot allocation

## 19. Can Both Robots Operate Concurrently?

Yes, in a limited form.

Each robot can own one task. The downstream robot may pre-stage at
`downstream_exit` while the upstream robot carries the package toward transfer.

The transfer lease prevents both robots from entering the shared transfer zone
simultaneously.

## 20. Where Is Collaboration Implemented?

Collaboration is mediated through shared mission state:

```text
Robot outcome
    ↓
Package/resource state changes
    ↓
Another task becomes eligible
    ↓
Another robot receives work
```

There is no direct robot-to-robot negotiation message. The centralized mission
manager coordinates them through package state, task readiness, and transfer
access.

## 21. What Constraints Exist?

| Constraint | Enforced by |
|---|---|
| Fixed robot role | Mission factory |
| Task may start | Scheduler |
| Steps execute in order | Behavior-tree memory sequence |
| Robot owns one task | Robot assignment state |
| Task has one active command | `active_command_id` |
| Transfer has one lease | Resource manager |
| Transfer has one robot | Robot capacity and occupancy |
| Transfer has one package | Package capacity and occupancy |
| Correct package must exist | Pickup access rule |
| Movement must reach target | Nav2 arrival validation |
| Physical traffic conflicts | RMF and Nav2 |

## 22. How Is Transfer Access Enforced?

Before entering transfer, a task requests access with:

```text
robot
task
purpose: pickup or dropoff
package
```

The resource manager returns:

```text
GRANTED
WAIT
BLOCKED
```

On `GRANTED`, a lease records permission and intent.

After arrival, robot occupancy is recorded. After package handling, package
occupancy is updated. The robot then exits to its directional clear point before
the occupancy and lease are released.

## 23. Why Separate Lease From Occupancy?

They describe different states:

```text
Lease:
  permission to approach and use transfer

Occupancy:
  robot is logically inside transfer
```

Without a lease, two robots could both decide to approach an empty resource
before either one is marked physically present.

## 24. How Does Waiting Work?

When access is unavailable:

- the resource manager identifies the reason
- it returns a robot-specific wait waypoint if available
- the BT moves the robot there
- the task records blocker and recovery information

Examples:

```text
PACKAGE_NOT_AVAILABLE
TRANSFER_PACKAGE_FULL
TRANSFER_ROBOT_OCCUPIED
WAITING_FOR_TRANSFER_LEASE
```

Current weakness: blocked tasks are reconsidered when another event advances
the mission. There is no dedicated resource-event wakeup mechanism.

## 25. What Are the Important Invariants?

```text
One robot owns at most one active mission task.
One task has at most one active external command.
Only one robot may lease transfer.
Only one robot may occupy transfer.
Only one package may be buffered at transfer.
A transfer pickup requires the requested package.
A task succeeds only after all workflow steps succeed.
The mission completes only after all tasks succeed.
Logical location changes only after verified movement.
```

These are logical in-process invariants, not physical safety interlocks.

## 26. What Is `MissionWorld`?

`MissionWorld` is the mission layer's belief state:

- logical robot waypoint and availability
- package location and carrier
- transfer lease and occupancy

It is needed because RMF does not own package semantics.

It should not be described as guaranteed physical truth. It is updated from
accepted execution outcomes and currently lacks continuous reconciliation.

## 27. What Is the Source of Truth?

There are separate owners:

| State | Owner |
|---|---|
| Mission and task workflow | Mission manager |
| Logical package/resource state | Mission world |
| Execution-command state | Execution manager |
| RMF task lifecycle | RMF |
| Navigation outcome | Free Fleet/Nav2 |
| UI representation | Serializer projection |

The mission manager is authoritative for logical mission state during one
process lifetime. There is no durable unified source of truth across restart.

## 28. Why Does RMF Completion Not Complete Movement?

RMF task summaries describe lifecycle but do not provide sufficient final-pose
evidence for package handling.

The mission waits for a robot-side result containing:

```text
expected Nav2 source
arrival_verified = true
```

This prevents a weak lifecycle signal from starting load or unload prematurely.

## 29. How Is Package Handling Confirmed?

The mission emits a `HANDLE_ITEM` command and waits for an external result.

The mission package itself does not physically verify the package. Confirmation
may come from simulation, an actuator, a sensor, or an operator.

This is a known maturity gap. A production system should identify the
confirmation source and confidence and reconcile ambiguous handling outcomes.

## 30. Is the Transfer Lease a Safety Mechanism?

It is a logical coordination mechanism, not a certified safety system.

Physical safety still depends on:

- RMF graph and mutex configuration
- traffic negotiation
- Nav2 collision avoidance
- localization
- robot safety controls

A mature physical system may require region sensors, geofencing, safety-rated
controls, and conservative behavior during communication loss.

## 31. How Are Duplicate Results Handled?

Execution commands reject repeated terminal transitions, so a duplicate success
message normally does not advance the mission twice.

This does not guarantee exactly-once physical execution. If a robot performs an
operation and its result is lost, retry behavior may be ambiguous.

## 32. What Happens If a Result Is Lost?

The command may remain active indefinitely because there is no general timeout
and reconciliation mechanism.

Needed improvements:

- command deadlines
- timeout events
- robot-side status query
- reconciliation before retry
- operator escalation for ambiguous handling

## 33. What Happens If the Mission Manager Crashes?

The in-memory runtime is lost. Restart creates a fresh mission.

This is one of the largest gaps between the prototype and a mature system.

Required improvements:

- durable mission and command state
- stable command IDs
- startup reconciliation with RMF and robots
- recovery policy for packages and leases

## 34. How Do Pause and Resume Work?

Mission pause:

- changes mission status to `PAUSED`
- requests cancellation of active moves
- suppresses follow-up commands

If a command completes during pause, its successful effect is still applied.
Resume returns the mission to `RUNNING` and advances from stored task and BT
state.

Per-robot pause affects only one robot, allowing other robots to continue.

## 35. How Does Abort Work?

Current abort:

- marks the mission `ABORTED`
- marks unfinished tasks `CANCELLED`
- requests active movement cancellation

It does not fully reconcile:

- active leases
- robot ownership
- package location
- physical handling state

A mature abort should be an explicit cancellation and reconciliation workflow,
not only a status transition.

## 36. Is the System Production-Ready?

No.

It is appropriate for controlled validation of the fixed two-robot handoff. It
lacks persistence, restart recovery, comprehensive timeouts, physical package
verification, generalized configuration, and complete recovery semantics.

## 37. Is the Architecture Scalable?

The separation of responsibilities supports evolution, but the implementation
does not scale directly:

- one in-memory runtime
- one centralized process
- fixed roles
- sorted-first scheduling
- one simple resource lease
- no distributed ownership

Scaling requires architectural work rather than only configuration changes.

## 38. What Decisions Are Sound Enough to Keep?

- Mission policy separated from ROS transport.
- Scheduler separated from task execution.
- External work represented as commands.
- State updated after accepted outcomes.
- Transfer modeled as an explicit domain resource.
- Lease separated from robot and package occupancy.
- Verified navigation arrival.
- Operator-visible blockers and expected recovery.
- Compact state separated from debug state.

## 39. What Would Need Redesign?

- Hard-coded mission topology and robot roles.
- Task-ID ordering as scheduling policy.
- Volatile mission and command state.
- Sequential command IDs that reset.
- Opportunistic blocked-task wakeup.
- Side-channel movement correlation.
- Lack of timeout and reconciliation.
- Incomplete abort and recovery behavior.
- Lack of physical package observation.
- Simple one-lease resource policy.

## 40. What Should Be Improved First?

For continued physical testing:

1. Add command and lease timeouts.
2. Convert RMF rejection into explicit mission failure.
3. Add resource-change wakeup events.
4. Reconcile leases and robot state during abort.
5. Add operator correction and force-release actions.
6. Persist mission and command state.
7. Strengthen package handling confirmation.

Generalization and fleet optimization should follow after the fixed scenario is
reliable and recoverable.

## 41. How Should the Design Be Defended?

Separate answers into three categories.

### Intentional scope

```text
two robots
fixed roles
one transfer
one mission
in-memory runtime
simple deterministic scheduler
minimal behavior tree
```

### Architectural foundations

```text
layer separation
event-command loop
explicit resource model
mission-owned domain state
verified execution outcomes
observable blockers
```

### Known gaps

```text
persistence
restart recovery
dynamic allocation
timeouts
physical package verification
general mission configuration
distributed consistency
```

The credible position is:

> The current system optimizes for clarity and validation of one collaboration
> scenario. It establishes useful boundaries between mission policy, shared
> resource coordination, and robot execution, while deliberately postponing the
> persistence, recovery, configurability, and distributed-consistency mechanisms
> required by a mature general-purpose platform.

## 42. Short Closing Summary

The four mechanisms to remember are:

```text
Scheduler:
  decides which task may start

Behavior tree:
  decides the task's next step

Resource manager:
  decides whether shared access is allowed

Execution adapters:
  perform external work and report outcomes
```

They operate over:

```text
MissionRuntime + MissionWorld
```

The central collaboration mechanism is:

```text
package state + transfer lease + task readiness
```

The central enforcement principle is:

> Check constraints before emitting an action, and update logical state only
> after receiving a valid execution result.
