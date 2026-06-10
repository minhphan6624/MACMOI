# Strengthening the Current Mission Layer for Collaborative Multi-Robot Delivery

## 1. Current architectural position

The current system should be understood as a **centralized mission-control architecture with robot-local navigation execution**.

The central PC currently runs the mission layer, RMF, and fleet adapters. The robots mainly run hardware bringup, localization, and Nav2. In this setup, the collaboration logic lives centrally: the mission layer decides which task can start, whether the transfer zone can be entered, whether a package is available, which robot should wait, and when a task succeeds.

This is a valid architecture for the project because the main goal is to support a human operator interface for supervising collaborative robot missions. A centralized mission layer gives the interface one coherent source of truth.

Recommended label:

```text
Centralized mission coordination with RMF-mediated fleet execution and robot-local Nav2 execution.
```

---

## 2. Main design direction

The system does not need to become fully decentralized to demonstrate collaboration. The stronger direction is to make the centralized mission layer a better **collaboration authority**.

The mission layer should explicitly represent:

- task dependencies
- package ownership
- resource ownership
- blocked tasks
- waiting reasons
- transfer-zone access
- staging behavior
- recovery options
- operator interventions

The key goal is to move from:

```text
A working source-to-transfer-to-destination sequence
```

into:

```text
An explicit collaborative mission model with dependencies, resources, states, and explanations.
```

---

## 3. Current implementation strengths

The current implementation already has a useful separation of concerns:

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

## 4. Make task dependencies explicit

The current task structure already separates each package into two transport tasks:

```text
P1:source_to_transfer
P1:transfer_to_destination
```

This should be extended so that the dependency between these tasks is explicit rather than only implied by package location.

Example:

```json
{
  "task_id": "P1:transfer_to_destination",
  "depends_on": ["P1:source_to_transfer"],
  "preconditions": [
    "P1.location == transfer",
    "transfer.package_buffer contains P1",
    "tb3_2.status == IDLE",
    "transfer.robot_slot available"
  ],
  "blocked_reason": "P1 is not yet available at transfer",
  "unblock_condition": "P1 is unloaded at transfer and transfer robot slot is available"
}
```

This helps the system and dashboard answer:

```text
Why is this robot waiting?
What is it waiting for?
Which task or resource is blocking it?
What event will unblock it?
```

---

## 5. Promote reservations into first-class resource control

The transfer zone should not be controlled only by current occupancy. It should use explicit reservations or leases.

Current-style question:

```text
Is the transfer zone occupied right now?
```

Better mission-layer question:

```text
Who owns the right to use the transfer zone next, for what purpose, and for how long?
```

Recommended transfer resource model:

```json
{
  "resource_id": "transfer",
  "robot_capacity": 1,
  "package_capacity": 1,
  "current_robot": null,
  "stored_package": "P1",
  "active_lease": {
    "holder": "tb3_2",
    "task_id": "P1:transfer_to_destination",
    "purpose": "pickup",
    "expires_at": "..."
  },
  "queue": [
    {
      "robot_id": "tb3_1",
      "task_id": "P2:source_to_transfer",
      "purpose": "dropoff"
    }
  ]
}
```

The resource manager should support:

- lease request
- lease grant
- lease renewal
- lease release
- lease timeout
- queueing
- forced release by operator
- blocked-task explanation

Useful lease states:

```text
REQUESTED
GRANTED
ACTIVE
RELEASED
EXPIRED
CANCELLED
FAILED
```

This avoids stale reservations and helps recover from failures.

The resource manager should also track intent before navigation:

```text
tb3_1 requests dropoff reservation for P1 at transfer
tb3_2 requests pickup reservation for P1 at transfer
resource grants one active actor at a time
waiting actors remain queued or prioritized
```

This makes access deterministic and reduces race-like behavior between robots
that are simultaneously approaching or waiting near transfer.

---

## 6. Make blocking and waiting visible

Blocked tasks should be explicit mission objects, not just internal behavior-tree outcomes.

Example blocked-task state:

```json
{
  "task_id": "P1:transfer_to_destination",
  "status": "BLOCKED",
  "blocked_reason": "PACKAGE_NOT_AVAILABLE",
  "blocked_by": {
    "task_id": "P1:source_to_transfer",
    "robot_id": "tb3_1",
    "resource_id": "transfer"
  },
  "waiting_at": "staging",
  "unblock_condition": "P1 buffered at transfer and transfer robot slot available",
  "next_expected_event": "tb3_1 unloads P1 at transfer"
}
```

This is important for the operator dashboard. The dashboard should not only show:

```text
tb3_2: waiting
```

It should show:

```text
tb3_2 is waiting at staging.
Reason: P1 is not yet available at transfer.
Blocked by: tb3_1 source_to_transfer.
Next expected event: tb3_1 unloads P1 at transfer.
```

Blocked tasks should also be woken by relevant state-change events instead of
only being retried through broad orchestrator ticks:

```text
package buffered at transfer
transfer robot occupancy released
transfer package occupancy released
robot reached staging
```

This makes mission progression easier to reason about and gives the dashboard a
clearer explanation of what changed.

---

## 7. Replace optimistic package handling with confirmations

The current mission world is optimistic: it updates robot and item state when commands are reported complete. This is acceptable for early development, but collaborative supervision benefits from stronger confirmation.

Package and robot state should distinguish between:

```text
believed
confirmed
unverified
stale
failed
```

Example package state:

```json
{
  "package_id": "P1",
  "location": "transfer",
  "holder": null,
  "state_confidence": "confirmed",
  "last_confirmed_by": "tb3_1",
  "last_confirmed_at": "..."
}
```

Confirmation sources could include:

- robot-side sensor feedback
- pickup/dropoff actuator state
- simulation truth state
- fiducial marker detection
- operator confirmation
- fleet adapter feedback

Even if the first version still uses simulated confirmation, the mission model should reserve space for this distinction.

Useful runtime validation checks include:

```text
robot reached expected waypoint before completing move
robot is not physically in transfer when resource says free
item handling succeeded before item state changes
```

This matters because the current mission state is logical, not a physical truth
source.

---

## 8. Keep the mission-level BT central

The current mission-task behavior tree should mostly remain on the central PC because it contains mission-level logic:

```text
AssignRobot
RequestResourceAccess
MoveTo
HandleItem
ReleaseResourceIfManaged
ReleaseRobot
MarkTaskSucceeded
```

These steps depend on shared mission state, shared resources, package state, and task progression. Moving the full mission BT onto each robot would push the system toward decentralized mission control and would require distributed locking, shared-state synchronization, conflict resolution, and more complex recovery.

Recommended split:

```text
Central PC:
mission-level BT, task dependencies, resource access, package ownership, mission progression

Robot:
local command execution, Nav2 monitoring, safety, local recovery, pickup/dropoff confirmation
```

A future robot-side executor could run a smaller execution BT:

```text
ExecuteMoveCommand
  -> validate command
  -> send goal to Nav2
  -> monitor progress
  -> retry local recovery
  -> report result
```

This strengthens the hybrid architecture without decentralizing the mission layer.

The current custom BT is still appropriate while the tree is compact and tightly
integrated with the mission task model. If task logic grows into many
fallback/retry/recovery branches, reassess whether a mature BT library such as
`py_trees` would be useful.

Good reasons to switch later:

```text
visualization
tree introspection
standard composites/decorators
blackboard tooling
runtime debugging
larger recovery behaviors
```

---

## 9. Add structured failure and recovery handling

The mission layer should distinguish different failure types instead of treating all failures as generic task failure.

Useful cases:

- robot failed before pickup
- robot failed while carrying package
- robot failed inside transfer
- robot failed after unloading package
- package missing at pickup
- package stuck at transfer
- transfer occupied too long
- RMF task rejected
- RMF movement task failed
- robot stuck or timed out
- handling timeout
- operator cancels or pauses a task

Example recovery state:

```json
{
  "task_id": "P1:source_to_transfer",
  "status": "FAILED_NEEDS_RECOVERY",
  "failure_type": "ROBOT_FAILED_WHILE_CARRYING_PACKAGE",
  "affected_robot": "tb3_1",
  "affected_package": "P1",
  "resource_to_release": "transfer",
  "operator_actions": [
    "retry",
    "reassign_robot",
    "mark_package_recovered",
    "abort_package_delivery"
  ]
}
```

This is especially important for HRI because failures are when the operator most needs a clear explanation and actionable choices.

---

## 10. Strengthen the scheduler

The current scheduler is deterministic and simple. It can be extended into a dependency-aware scheduler.

It should eventually consider:

- task priority
- robot availability
- robot capability
- package location
- transfer-zone lease state
- queue position
- estimated travel time
- blocked duration
- pre-staging opportunity
- battery level
- operator priority

This allows the mission layer to make better choices, such as:

```text
send the downstream robot to staging before the package arrives
prioritize a package with an earlier deadline
delay a robot if the transfer queue is full
assign a backup robot if the original robot fails
```

Waiting behavior should also be configurable per resource or mission profile:

```text
wait_at = staging
wait_at = home
wait_at = current_position
prestage_downstream = true/false
```

For the lab handoff, pre-staging `tb3_2` can improve throughput if staging is
near transfer and does not block the shared path. For other maps, waiting at
home may be safer.

---

## 11. Generalize from fixed robots to roles and capabilities

The current default mission assigns fixed roles:

```text
tb3_1 = source_to_transfer
tb3_2 = transfer_to_destination
```

For a more general collaborative fleet system, task roles should be separated from specific robot identities.

Instead of:

```json
{
  "task_id": "P1:source_to_transfer",
  "robot_id": "tb3_1"
}
```

Use:

```json
{
  "task_id": "P1:source_to_transfer",
  "required_capabilities": [
    "can_navigate_source_area",
    "can_carry_package"
  ],
  "preferred_robot": "tb3_1",
  "assigned_robot": null
}
```

This supports:

- backup robots
- larger fleets
- mixed robot capabilities
- operator reassignment
- failure recovery
- dynamic task allocation

---

## 12. Align mission resources with RMF movement constraints

The mission layer should remain the authority for semantic rules such as package handoff and transfer-zone ownership. RMF should remain responsible for movement, traffic planning, and navigation execution.

However, the RMF graph and mission resource model should not contradict each other.

Recommended improvements:

- represent transfer as a controlled waypoint or region
- add staging waypoint as an intentional queue location
- prevent unrelated traffic from casually routing through transfer
- consider RMF mutexes or graph design to support mission-layer resource rules
- separate transfer ingress and egress if needed

The mission layer should decide who may use transfer. RMF should help ensure the physical movement plan respects that decision.

RMF traffic negotiation and mission resource rules remain separate. Poor graph
layout, missing mutex groups, or staging on a bottleneck can still cause bad
traffic behavior even when the mission-layer resource rules are correct.

---

## 13. Improve the dashboard-facing mission state

The operator interface should expose collaboration, not just robot motion.

The mission-state API should include:

- active task dependencies
- blocked tasks
- blocked reasons
- resource owner
- resource queue
- active leases
- package holder
- package confidence
- waiting robots
- next expected event
- available operator interventions

Example dashboard card:

```text
tb3_2 waiting at staging
Reason: P1 not yet available at transfer
Blocked by: tb3_1 source_to_transfer
Transfer state: reserved by tb3_1 for dropoff
Next event: tb3_1 unloads P1 at transfer
Available actions: pause, reassign, inspect robot, force release
```

This turns the dashboard from a fleet monitor into a mission coordination interface.

---

## 14. Suggested implementation order

### Step 1: Add explicit return-home behavior

Add mission-layer return-home commands after all package transport tasks
succeed:

```text
tb3_1 -> robot1_home
tb3_2 -> robot2_home
mission COMPLETED only after both robots reach home
```

This is clearer than relying on RMF or fleet-adapter finishing behavior.

### Step 2: Add explicit dependency and blocked-state fields

Add fields such as:

```text
blocked_reason
blocked_by
unblock_condition
waiting_at
next_expected_event
depends_on
preconditions
```

This gives immediate value to the mission layer and dashboard.

### Step 3: Make reservations and leases primary

Upgrade `WorldResourceManager` so transfer access is based on:

```text
leases
queues
ownership
timeouts
release rules
```

This is the most important change for shared-resource collaboration.

### Step 4: Add event-driven wakeups and configurable waiting policy

Wake blocked tasks when package, resource, robot, or staging state changes.
Configure waiting behavior per mission or resource so robots can wait at
staging, home, or their current position as appropriate for the map.

### Step 5: Add failure, cancellation, pause, and recovery paths

Extend the orchestrator, BT runner, execution manager, and RMF adapter so task failures become structured states with recovery options.

### Step 6: Replace simulated handling timers

Replace fake `HANDLE_ITEM` completion with real, simulated, or operator-confirmed pickup/dropoff confirmation.

### Step 7: Introduce capabilities and dynamic assignment

Move from fixed robot-task assignment to role/capability-based allocation.

### Step 8: Improve the dashboard API

Expose dependency, resource, lease, blocked, confidence, and intervention state to the UI.

### Step 9: Reassess BT tooling

Keep the custom BT while the tree remains small. If recovery behavior becomes
large enough to need visualization, introspection, standard composites, or
blackboard tooling, consider migrating to `py_trees`.

---

## 15. Recommended target architecture

```text
Central mission layer:
  explicit task dependencies
  resource leases and queues
  package ownership
  blocked-state explanations
  recovery decisions
  operator-facing mission state

RMF:
  traffic-aware movement execution
  fleet movement coordination
  task request handling

Robots:
  hardware bringup
  localization
  Nav2
  local safety
  local recovery
  physical action confirmation
  structured status reporting

Dashboard:
  dependency view
  resource view
  blocked/waiting explanations
  operator intervention controls
```

---

## 16. Main takeaway

The best next step is not to fully decentralize the system. The best next step is to strengthen the centralized mission layer so that collaboration is:

```text
explicit
observable
recoverable
generalizable
operator-controllable
```

The current architecture is already a reasonable foundation. The next version should make task dependency, resource ownership, package state, waiting behavior, and recovery logic first-class parts of the mission model.
