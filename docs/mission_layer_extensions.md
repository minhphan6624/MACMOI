# Mission Layer Extensions

This document records near-term improvement ideas for the current mission layer.
It focuses on multi-robot collaboration, transfer-zone correctness, and runtime
robustness.

---

## Current Strengths

The current implementation has a useful separation of concerns:

```text
MissionOrchestrator:
  mission lifecycle and task coordination

TransportTaskScheduler:
  ready-task selection

TransportTaskBtRunner:
  per-task execution behavior

RuntimeWorld:
  mission-layer robot/item/resource state

WorldResourceManager:
  transfer-zone access decisions

RmfExecutionAdapter:
  RMF task API boundary
```

The transfer zone is no longer only an implicit waypoint. It is a mission-layer
resource with robot capacity, package capacity, and a wait waypoint. That gives
the mission layer a clear place to enforce rules such as:

```text
do not enter transfer if another robot is there
do not enter transfer for pickup if no package is buffered there
do not drop off if transfer already contains a package
wait at staging when transfer access is unavailable
```

The BT runner also makes the transport workflow easier to inspect and extend
than a larger mission-specific FSM.

---

## Current Pitfalls

The mission world is optimistic. It trusts command completion reports and then
updates internal state. It does not continuously verify robot pose, package
state, or whether the physical transfer zone is actually clear.

The resource model has reservation fields, but the current runtime mainly uses
occupancy and package buffering. That is enough for the simple two-robot demo,
but it is not yet a full reservation/queue system.

Blocked tasks are retried through normal orchestrator ticks. There is no
explicit event such as:

```text
resource transfer changed -> wake tasks waiting on transfer
```

The scheduler is deterministic but basic. It sorts task IDs and starts the first
eligible task. It does not yet reason about fairness, robot proximity,
throughput, package priority, or staging congestion.

RMF traffic negotiation and mission resource rules remain separate. The mission
layer can decide that a robot should wait at staging, but RMF still controls the
physical route to staging and transfer. Poor graph layout, missing mutex groups,
or staging on a bottleneck can still cause bad traffic behavior.

End-of-mission behavior is incomplete. The mission layer marks the mission
complete when all transport tasks succeed, but it does not explicitly command
robots back to their home waypoints.

---

## Recommended Improvements

### 1. Explicit Return-Home Behavior

Add mission-layer return-home commands after all package transport tasks
succeed:

```text
tb3_1 -> robot1_home
tb3_2 -> robot2_home
mission COMPLETED only after both robots reach home
```

This is clearer than relying on RMF/fleet-adapter finishing behavior.

### 2. Reservation-Based Resource Access

Promote the existing reservation model into the main transfer-zone coordination
mechanism.

The resource manager should track intent before navigation:

```text
tb3_1 requests dropoff reservation for P1 at transfer
tb3_2 requests pickup reservation for P1 at transfer
resource grants one active actor at a time
waiting actors remain queued or prioritized
```

This would make access deterministic and reduce race-like behavior between
robots that are simultaneously approaching or waiting near transfer.

### 3. Event-Driven Wakeups

Wake blocked tasks when relevant state changes:

```text
package buffered at transfer
transfer robot occupancy released
transfer package occupancy released
robot reached staging
```

This would reduce dependence on broad ticks and make the mission progression
easier to reason about.

### 4. Configurable Waiting Policy

Make waiting behavior configurable per resource or mission profile:

```text
wait_at = staging
wait_at = home
wait_at = current_position
prestage_downstream = true/false
```

For the lab handoff, pre-staging `tb3_2` can improve throughput if staging is
near transfer and does not block the shared path. For other maps, waiting at
home may be safer.

### 5. Stronger Runtime Validation

Use fleet state or robot telemetry to validate mission assumptions:

```text
robot reached expected waypoint before completing move
robot is not physically in transfer when resource says free
item handling succeeded before item state changes
```

This matters because the current mission state is logical, not a physical truth
source.

### 6. Failure, Timeout, and Cancellation Paths

Add behavior for:

```text
RMF task rejected
RMF task failed
robot stuck or timed out
handling timeout
operator abort
operator pause/resume
```

The current happy path is useful, but real multi-robot runs need explicit
recovery behavior.

### 7. Cleaner BT Growth Path

Keep the current minimal BT while the behavior remains small. If the task logic
grows into many fallback/retry/recovery branches, consider moving to a mature
BT library such as `py_trees`.

Good reasons to switch later:

```text
visualization
tree introspection
standard composites/decorators
blackboard tooling
runtime debugging
larger recovery behaviors
```

The current custom BT is still appropriate while the tree is compact and tightly
integrated with the mission task model.

---

## Suggested Implementation Order

Recommended order:

```text
1. Add explicit return-home behavior.
2. Make transfer access reservation/queue based.
3. Add event-driven wakeups for blocked tasks.
4. Make waiting/pre-staging policy configurable.
5. Add physical-state validation from fleet state or robot telemetry.
6. Add timeout, failure, cancellation, and recovery handling.
7. Reassess whether the minimal BT should be replaced by py_trees.
```

The main design target is stronger synchronization between:

```text
mission intent
resource access
RMF traffic execution
physical robot/package state
```
