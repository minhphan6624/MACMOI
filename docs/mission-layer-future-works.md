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
- directional wait/clear behavior
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
MissionManager:
  mission lifecycle and task coordination

TransportTaskScheduler:
  ready-task selection

TransportTaskBtRunner:
  per-task execution behavior

MissionWorld:
  mission-layer robot/item/resource state

ResourceManager:
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
wait at the robot's directional exit/wait point when transfer access is unavailable
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
  "waiting_at": "downstream_exit",
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
tb3_2 is waiting at downstream_exit.
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
robot reached its directional wait point
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

## 9. Add an execution backend switch for reduced RMF usage

The current system uses RMF as the movement execution bridge between the mission layer and Nav2. When the mission layer emits a `MOVE_ROBOT` command: 
  - the ROS node publishes mission execution context and also submits an RMF task API request. 
  - RMF task dispatching accepts the request, 
  - the Free Fleet adapter receives a `go_to_place` command, 
  - the adapter sends a Nav2 `NavigateToPose` goal, 
  - and completion is reported back through RMF task summaries and the mission execution result channel.

This is useful because it keeps the system aligned with RMF task and fleet infrastructure. However, for the current TurtleBot3-only handoff workflow, RMF is not the source of truth for collaboration semantics. The mission layer
already decides:

* which robot owns the transfer resource
* whether a package is available at transfer
* whether transfer has package capacity
* which robot should wait at the directional exit/wait point
* why a task is blocked
* what event will unblock it


RMF traffic scheduling can protect physical lane usage, but it does not naturally express handoff-specific states such as `PACKAGE_NOT_AVAILABLE`, `TRANSFER_PACKAGE_FULL`, or `WAITING_FOR_TRANSFER_LEASE`. For the intended use case, the explicit mission/resource logic should remain authoritative.

The recommended future change is to add an execution backend switch: `execution_backend = rmf | direct_nav2`

In `rmf` mode, the system keeps the current behavior:

```text
MissionManager
  -> MOVE_ROBOT
  -> mission_execution_commands
  -> RMF task_api_request
  -> rmf_task_dispatcher
  -> Free Fleet adapter
  -> Nav2 NavigateToPose
  -> task_summaries / mission_execution_results
  -> MissionManager.complete_command(...)
```

In `direct_nav2` mode, the movement path should bypass RMF task dispatching:

```text
MissionManager
  -> MOVE_ROBOT
  -> mission_execution_commands
  -> direct Nav2 command bridge
  -> Nav2 NavigateToPose
  -> mission_execution_results
  -> MissionManager.complete_command(...)
```

The mission workflow does not change significantly between the two modes. The same mission tasks, resource leases, blocked states, and package state should be used. Only the command execution boundary changes.

The main differences are:

```text
RMF backend:
  uses RMF task dispatching, RMF task IDs, task summaries, Free Fleet, and the
  RMF nav graph/lane model

direct_nav2 backend:
  uses mission command IDs, waypoint-to-pose lookup, direct Nav2 goals, and
  mission_execution_results as the completion source
```

The direct Nav2 backend would require a small waypoint-pose configuration in the Nav2 `map` frame. 
Nav2 can use the normal TurtleBot3 occupancy map directly; it does not need the RMF annotated building map for navigation. 

The RMF building map and nav graph can still be kept for fallback RMF execution, comparison experiments, or dashboard map display, but they should not be the navigation source of truth in direct Nav2 mode.

Implementation changes:

- add an `execution_backend` parameter to the mission manager node
- keep the current RMF adapter path for `rmf` mode
- add a direct Nav2 execution bridge for `direct_nav2` mode
- add a waypoint-name to Nav2-pose YAML file
- complete movement from `mission_execution_results` in direct mode
- avoid relying on RMF `task_summaries` as the mission source of truth
- keep mission-state publication stable for the dashboard

RMF modules for the intended use case:

```text
building_map_server:
  use for existing dashboard map display and RMF map compatibility

Free Fleet / fleet state reporting:
  use while the web UI still needs RMF-style robot fleet visibility

rmf_traffic_schedule:
  keep while the current Free Fleet adapter is retained, because the adapter
  expects RMF schedule infrastructure; otherwise optional for this fixed
  mission workflow

RMF nav graph and annotated building map:
  keep for RMF fallback mode, dashboard display, and comparison experiments;
  do not use as the navigation source of truth in direct_nav2 mode

RMF task API / task summaries:
  use in rmf backend mode and for comparison; do not rely on them as the
  mission completion source in direct_nav2 mode
```

RMF modules that are not central to the intended use case:

```text
rmf_task_dispatcher:
  bypass in direct_nav2 mode because the mission manager already owns task
  lifecycle and command tracking

RMF lane traffic coordination and transfer mutexes:
  optional as defensive movement coordination, but not the authority for
  transfer ownership, package buffering, or blocked-task explanations

delivery, clean, compose UI/task variants beyond go_to_place:
  not needed for the current fixed package handoff workflow

doors, lifts, dispensers, ingestors, beacons, workcells:
  not needed unless the physical lab setup later adds those systems

Gazebo/RMF demo worlds:
  not needed for the physical TurtleBot3 deployment except as optional
  development or comparison tools
```

If RMF is reduced gradually, the likely steady state is:

```text
Kept:
  mission_manager
  Nav2
  operator dashboard
  building map display
  optional fleet-state bridge

Bypassed or optional:
  rmf_task_dispatcher
  RMF task summaries as the mission completion source
  RMF lane-level scheduling for transfer conflict ownership

Removed only after replacement exists:
  Free Fleet state reporting
  rmf_traffic_schedule
  RMF map/fleet API dependencies used by the web UI
```

Notes
- Reducing RMF task dispatching would make RMF task panels less meaningful unless equivalent custom task state is provided. 
- Map display can still be supported through the RMF building map server or a custom map source. 
- Robot fleet information can still come from Free Fleet/RMF while that adapter is retained, but if RMF traffic scheduling and Free Fleet are removed entirely, the project will need a custom robot-state API or websocket stream for the dashboard.

Migration path:

```text
short term:
  keep RMF mode as the known-working fallback
  add direct_nav2 mode for the TurtleBot3 mission workflow

medium term:
  make the custom mission dashboard depend primarily on mission_state,
  mission commands, robot state, and mission execution results

long term:
  decide whether RMF remains as map/fleet visualization infrastructure,
  comparison baseline, or is removed from the runtime entirely
```

---

## 10. Add structured failure and recovery handling

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

### Current gap: command failure does not yet drive task recovery

The code already has failure-oriented states such as `MissionTaskStatus.FAILED`
and `ExecutionCommandStatus.FAILED`, but the transport behavior tree currently
only returns:

```text
SUCCESS
RUNNING
```

There is no behavior-tree failure result and no fallback/recovery branch yet.
When an execution result reports `FAILED` or `CANCELLED`, the node can mark the
execution command failed, but the active task is not yet cleanly transitioned
through the mission manager and BT runner. That means the mission can stall
with a failed command while the task still looks active.

The first improvement should be explicit failed-command handling, not a large
fallback tree. Add a mission-manager entry point such as:

```python
MissionManager.handle_command_failed(command_id, error)
```

or represent it through the future event interface:

```python
MissionManager.handle_event(ExecutionCommandFailed(...))
```

That path should:

```text
mark the execution command failed
find the task that owns the command
clear task.active_command_id
store the failure reason on the task
set the task to FAILED or a recovery-needed state
set the mission to FAILED if the failure is unrecoverable
publish the updated mission_state
```

It may be worth adding `MissionStatus.FAILED` so runtime failure is distinct
from `ABORTED`, which should mean operator-initiated cancellation.

After failed-command handling is explicit, add focused recovery policies:

```text
move command failed
  -> retry a small number of times, then fail the task

RMF task rejected
  -> fail the command immediately or retry with backoff

resource unavailable
  -> keep the task BLOCKED/WAITING instead of failing

load/unload failed or timed out
  -> mark the task recovery-needed and ask for operator confirmation
```

Only add a richer fallback BT once these states and transitions are visible in
the mission state and useful to the dashboard/operator workflow.

---

## 11. Strengthen the scheduler

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
- pre-positioning opportunity
- battery level
- operator priority

This allows the mission layer to make better choices, such as:

```text
send the downstream robot to `downstream_exit` before the package arrives
prioritize a package with an earlier deadline
delay a robot if the transfer queue is full
assign a backup robot if the original robot fails
```

Waiting behavior should also be configurable per resource or mission profile:

```text
wait_at = directional_exit
wait_at = home
wait_at = current_position
prestage_downstream = true/false
```

For the lab handoff, pre-positioning `tb3_2` at `downstream_exit` can improve
throughput if that point does not block the shared path. For other maps,
waiting at home may be safer.

---

## 12. Generalize from fixed robots to roles and capabilities

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

## 13. Align mission resources with RMF movement constraints

The mission layer should remain the authority for semantic rules such as package handoff and transfer-zone ownership. RMF should remain responsible for movement, traffic planning, and navigation execution.

However, the RMF graph and mission resource model should not contradict each other.

Recommended improvements:

- represent transfer as a controlled waypoint or region
- add directional wait/clear waypoints as intentional queue locations
- prevent unrelated traffic from casually routing through transfer
- consider RMF mutexes or graph design to support mission-layer resource rules
- separate transfer ingress and egress if needed

The mission layer should decide who may use transfer. RMF should help ensure the physical movement plan respects that decision.

RMF traffic negotiation and mission resource rules remain separate. Poor graph
layout, missing mutex groups, or wait points on a bottleneck can still cause
bad traffic behavior even when the mission-layer resource rules are correct.

---

## 14. Improve the dashboard-facing mission state

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
tb3_2 waiting at downstream_exit
Reason: P1 not yet available at transfer
Blocked by: tb3_1 source_to_transfer
Transfer state: reserved by tb3_1 for dropoff
Next event: tb3_1 unloads P1 at transfer
Available actions: pause, reassign, inspect robot, force release
```

This turns the dashboard from a fleet monitor into a mission coordination interface.

---

## 15. Introduce an explicit mission event interface

The current mission manager is already event-driven, but the event handling is
implicit. Different ROS callbacks call different mission-manager methods:

```text
mission command start
  -> MissionManager.start()

RMF task summary / Nav2 result / robot handling result
  -> MissionManager.complete_command(command_id)

MissionManager.start() and MissionManager.complete_command(...)
  -> tick()
```

This is enough for the current fixed handoff because most meaningful progress
is caused by execution-command completion. It becomes harder to extend once the
mission depends on operator decisions, retries, timeouts, manual package
confirmation, robot availability changes, or external resource updates.

The next version should introduce one common mission-event entry point:

```python
MissionManager.handle_event(event) -> list[ExecutionCommand]
```

The ROS node should translate external callbacks into mission events, then let
the mission manager update state and emit any follow-up commands:

```text
ROS callback / robot result / timer / dashboard command
  -> MissionEvent
  -> MissionManager.handle_event(...)
  -> ExecutionCommand list
  -> MissionManagerNode dispatches commands
```

Start with only the events the current system already needs:

```text
MissionStartRequested
ExecutionCommandCompleted
ExecutionCommandFailed
```

Then add future events as features become real:

```text
OperatorPauseRequested
OperatorResumeRequested
OperatorAbortRequested
OperatorApproved
RetryTimerExpired
TaskTimeoutExpired
ManualPackageConfirmed
RobotAvailabilityChanged
ResourceStateChanged
```

Use a small hierarchy for grouping, but keep behavior-specific events explicit:

```text
MissionEvent
  OperatorEvent
    OperatorPauseRequested
    OperatorResumeRequested
    OperatorAbortRequested
  ExecutionEvent
    ExecutionCommandCompleted
    ExecutionCommandFailed
  TimerEvent
    RetryTimerExpired
    TaskTimeoutExpired
```

Avoid making the mission manager string-driven through a generic event such as:

```python
OperatorCommandEvent(command="pause")
```

If two cases produce different mission behavior, represent them as different
event classes. If they only differ by metadata, use one event class with fields.
For example, `ExecutionCommandCompleted` can carry `source =
"task_summary" | "nav2_result" | "robot_handling_simulator"` rather than
creating separate completion event classes for each source.

`handle_event(...)` should route events to focused private handlers instead of
becoming one large function:

```python
def handle_event(self, event):
    if isinstance(event, MissionStartRequested):
        commands = self._handle_start_requested(event)
    elif isinstance(event, ExecutionCommandCompleted):
        commands = self._handle_command_completed(event)
    elif isinstance(event, OperatorPauseRequested):
        commands = self._handle_operator_pause_requested(event)
    else:
        commands = []

    return self._advance_after_event(commands)
```

This keeps the useful event-driven model while making synchronization more
explicit. Parallelism still comes from multiple in-flight `ExecutionCommand`
objects. The mission manager only needs to wake when meaningful state changes:

```text
command completed
operator made a decision
retry delay expired
timeout expired
manual confirmation arrived
resource or robot state changed
```

This should be treated as a moderate orchestration refactor, not a full
architecture rewrite. `MissionWorld`, `ResourceManager`, `ExecutionManager`,
`TransportTaskScheduler`, `TransportTaskBtRunner`, and `RmfExecutionAdapter`
can mostly remain in their current roles.

---

## 16. Suggested implementation order

### Step 1: Add a small mission-event facade

Introduce `MissionEvent` classes and `MissionManager.handle_event(...)` for the
events the system already handles:

```text
MissionStartRequested
ExecutionCommandCompleted
ExecutionCommandFailed
```

Keep `start()` and `complete_command()` as compatibility wrappers at first, or
replace their call sites in `MissionManagerNode` directly. The goal is to
preserve current behavior while creating the extension point needed for
operator decisions, retries, timeouts, and manual confirmations.

### Step 2: Add explicit return-home behavior

Add mission-layer return-home commands after all package transport tasks
succeed:

```text
tb3_1 -> robot1_home
tb3_2 -> robot2_home
mission COMPLETED only after both robots reach home
```

This is clearer than relying on RMF or fleet-adapter finishing behavior.

### Step 3: Add explicit dependency and blocked-state fields

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

### Step 4: Make reservations and leases primary

Upgrade `ResourceManager` so transfer access is based on:

```text
leases
queues
ownership
timeouts
release rules
```

This is the most important change for shared-resource collaboration.

### Step 5: Add event-driven wakeups and configurable waiting policy

Wake blocked tasks when package, resource, robot, or wait-point state changes.
Configure waiting behavior per mission or resource so robots can wait at a
directional exit, home, or their current position as appropriate for the map.

### Step 6: Add failure, cancellation, pause, and recovery paths

Extend the orchestrator, BT runner, execution manager, and RMF adapter so task failures become structured states with recovery options.

Start by wiring failed execution commands into the mission manager and BT
runner. The initial behavior can simply mark the owning task `FAILED`, clear
its active command, record the failure reason, and mark the mission `FAILED`
when recovery is not available. Add retries and fallback branches only after
that failure path is explicit and visible in `mission_state`.

### Step 7: Replace simulated handling confirmation

The mission manager now waits for robot-side `HANDLE_ITEM` results instead of
self-completing load/unload with local timers. The remaining work is replacing
the robot-side simulator result with real hardware, sensor, simulator-truth, or
operator-confirmed pickup/dropoff confirmation.

### Step 8: Introduce capabilities and dynamic assignment

Move from fixed robot-task assignment to role/capability-based allocation.

### Step 9: Improve the dashboard API

Expose dependency, resource, lease, blocked, confidence, and intervention state to the UI.

### Step 10: Reassess BT tooling

Keep the custom BT while the tree remains small. If recovery behavior becomes
large enough to need visualization, introspection, standard composites, or
blackboard tooling, consider migrating to `py_trees`.

---

## 17. Recommended target architecture

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

## 18. Main takeaway

The best next step is not to fully decentralize the system. The best next step is to strengthen the centralized mission layer so that collaboration is:

```text
explicit
observable
recoverable
generalizable
operator-controllable
```

The current architecture is already a reasonable foundation. The next version should make task dependency, resource ownership, package state, waiting behavior, and recovery logic first-class parts of the mission model.
