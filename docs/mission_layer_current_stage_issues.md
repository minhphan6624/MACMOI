# Mission Layer Current Stage Issues

This document records current mission-layer issues observed during test runs.
The focus is the shared transfer-zone and staging behavior in the two-robot
handoff mission.

## 1. Staging behavior is implicit

The current system can send a robot to `staging` when it requests access to
`transfer` and the resource manager returns `WAIT`.

This is useful, but the behavior is currently a fallback inside the transport
task BT rather than an explicit mission policy.

Current behavior:

```text
task requests transfer access
transfer cannot be granted
resource manager returns WAIT with staging waypoint
BT sends robot to staging
task becomes BLOCKED
task retries when the mission advances again
```

Issue:

```text
The mission state does not clearly explain why the robot is waiting, who or what
is blocking it, or which event should unblock it.
```

Observed examples:

- `robot2` waits at staging because the next package is not yet available at
  transfer.
- `robot2` waits at staging because `robot1` is still occupying transfer.
- `robot1` waits at staging because `robot2` is still using transfer.
- `robot1` waits at staging because transfer already contains one package and
  the transfer package capacity is full.

## 2. Transfer access is mostly occupancy-based

The transfer zone currently checks robot occupancy and package occupancy when a
robot asks for access.

Current questions:

```text
Is a robot currently occupying transfer?
Is there package capacity at transfer?
Is the requested package buffered at transfer?
```

Issue:

```text
The mission layer does not yet strongly model who owns the next right to enter
transfer, for what purpose, and in what order.
```

This makes transfer coordination harder to reason about when both robots are
near the transfer workflow:

- upstream robot wants to drop off a new package
- downstream robot wants to pick up an existing package
- one robot is still inside transfer
- transfer already has a buffered package
- a robot is waiting at staging

Suggested direction:

```text
Make transfer access lease-based:
  active lease
  queue
  lease purpose: pickup or dropoff
  package id
  holder robot
  timeout/release rule
```

## 3. Waiting reasons are too coarse

Current task state can show that a task is `BLOCKED`, and the task can record
the resource and purpose it is waiting on.

Issue:

```text
Different blocked cases collapse into similar-looking waiting behavior.
```

Important cases that should be distinguishable:

- `TRANSFER_ROBOT_OCCUPIED`
- `TRANSFER_PACKAGE_FULL`
- `PACKAGE_NOT_AVAILABLE`
- `WAITING_FOR_TRANSFER_LEASE`
- `WAITING_FOR_ROBOT_TO_EXIT_TRANSFER`
- `WAITING_FOR_PACKAGE_PICKUP_CONFIRMATION`
- `WAITING_FOR_PACKAGE_DROPOFF_CONFIRMATION`

The dashboard and logs should be able to show:

```text
robot1 is waiting at staging
reason: TRANSFER_PACKAGE_FULL
blocked by: robot2 transfer_to_destination
next expected event: robot2 loads package from transfer
```

or:

```text
robot2 is waiting at staging
reason: PACKAGE_NOT_AVAILABLE
blocked by: robot1 source_to_transfer
next expected event: robot1 unloads package at transfer
```

## 4. Blocked tasks depend on broad mission advancement

When a task is blocked at staging, it is retried when the mission manager ticks
again. Ticks currently happen from mission start, command completions, handling
timers, and RMF/fleet callbacks.

Issue:

```text
The task is not woken by a specific resource/package event. It is retried when
some broader mission advancement happens.
```

This can work in the simple flow, but it makes the behavior less explicit and
harder to debug.

Suggested direction:

```text
Wake blocked tasks from specific state changes:
  package buffered at transfer
  package removed from transfer
  transfer robot slot released
  robot reached staging
  transfer lease released
  handling confirmation received
```

## 5. Staging is not modeled as a resource

The transfer resource has a `wait_waypoint`, currently `staging`.

Issue:

```text
The mission layer treats staging as a waypoint, not as a resource with its own
capacity or policy.
```

This matters if:

- both robots can be sent to the same staging waypoint
- staging blocks the transfer path
- upstream and downstream robots need different staging locations
- waiting at home is safer than waiting near transfer on some maps

Suggested direction:

```text
Make waiting policy configurable:
  wait_at = staging
  wait_at = home
  wait_at = current_position
  staging_capacity = 1
  upstream_staging = ...
  downstream_staging = ...
```

## 6. Resource release timing can reduce concurrency

Some transfer state changes happen only when the BT reaches later steps.

Issue:

```text
The mission-layer transfer state may remain occupied longer than the physical
handoff requires, which can delay the other robot.
```

Examples to review:

- after downstream pickup, transfer package capacity should become available as
  soon as pickup is confirmed
- after a robot exits transfer, robot occupancy should be released promptly
- after upstream dropoff, the package should become available only after dropoff
  is confirmed and the transfer buffer state is updated

Suggested direction:

```text
Tie resource state updates to explicit events:
  pickup confirmed
  dropoff confirmed
  robot entered transfer
  robot exited transfer
```

## 7. Desired target behavior

For upstream dropoff:

```text
robot1 loads package at source
robot1 requests transfer dropoff lease
if transfer robot slot or package slot is unavailable:
  robot1 moves to staging
  robot1 waits with an explicit blocked reason
when transfer becomes available:
  robot1 receives transfer lease
  robot1 moves from staging to transfer
  robot1 unloads package
  package is buffered at transfer
  robot1 exits transfer
  transfer lease is released
```

For downstream pickup:

```text
robot2 completes delivery
robot2 requests next transfer pickup lease
if package is not available or transfer is occupied:
  robot2 moves to staging
  robot2 waits with an explicit blocked reason
when package is buffered and transfer is available:
  robot2 receives transfer lease
  robot2 moves from staging to transfer
  robot2 loads package
  package is removed from transfer buffer
  robot2 exits transfer
  transfer lease is released
```

## 8. Recommended fix direction

The current architecture does not need to become fully decentralized. The
central mission layer can keep ownership of the collaboration rules.

Recommended improvements:

- add explicit transfer leases and queueing
- add structured blocked reasons and unblock conditions
- expose waiting state in mission state and dashboard data
- wake blocked tasks from resource/package/robot state-change events
- model staging as a configurable waiting policy/resource
- add a low-frequency watchdog only for stale state, timeouts, and missed events

The main goal is to move from:

```text
robot tried transfer, got WAIT, moved to staging
```

to:

```text
robot is waiting at staging because transfer/package state blocks its lease;
the mission layer knows what will unblock it and can explain that to the operator.
```

## 9. Proposed solutions discussed

### 9.1 Separate transfer lease from physical occupancy

The current transfer `robot_occupancy` acts partly like permission to use
transfer and partly like physical presence inside transfer.

This should be split into two concepts:

```text
lease:
  robot has permission or intent to use transfer for pickup/dropoff

occupancy:
  robot is considered physically inside the transfer conflict area
```

The resource manager should grant a lease before a robot is allowed to enter
transfer. Robot occupancy should represent the robot being inside the transfer
area, and should only be released when the robot is confirmed clear of that
area.

This avoids using one field for both scheduling intent and physical safety.

### 9.2 Add explicit transfer exit waypoints

The current system has no independent "clear of transfer" detection. A robot is
considered clear when the BT releases the transfer resource.

For the current architecture, the recommended short-term fix is to add explicit
exit waypoints, such as:

```text
transfer_upstream_exit
transfer_downstream_exit
```

Then release transfer robot occupancy only after the robot reaches the
appropriate exit waypoint.

Example upstream dropoff:

```text
move source -> transfer
unload package
buffer package at transfer
move transfer -> transfer_upstream_exit
release transfer robot occupancy
release transfer lease
mark source_to_transfer succeeded
```

Example downstream pickup:

```text
move staging -> transfer
load package
remove package from transfer buffer
move transfer -> transfer_downstream_exit
release transfer robot occupancy
release transfer lease
move transfer_downstream_exit -> destination
```

This is a practical substitute for true region/pose-based clearance.

### 9.3 Update package buffer state on handling confirmation

Package capacity should be updated when the load/unload action is confirmed,
not later due to generic BT cleanup ordering.

For upstream dropoff:

```text
on unload confirmed:
  robot no longer carries package
  package location = transfer
  package is buffered at transfer
  transfer package capacity is occupied
```

For downstream pickup:

```text
on load confirmed:
  package is removed from transfer buffer
  transfer package capacity is freed
  robot carries package
```

This allows the mission layer to distinguish:

```text
package is available/unavailable
robot is still occupying transfer
```

Those should not be the same state.

### 9.4 Release robot occupancy after exit confirmation, not action start

The mission layer should not release transfer robot occupancy when a robot merely
starts moving away from transfer.

Safer rule:

```text
release transfer robot occupancy only after the exit movement completes
```

This keeps the capacity rule meaningful:

```text
transfer.robot_capacity = 1
```

If the robot has started moving but is still crossing the transfer area, the
other robot should still be blocked from entering.

### 9.5 Reorder BT steps around transfer

The BT should make transfer state transitions match the physical meaning of each
step.

Recommended upstream dropoff order:

```text
request transfer dropoff lease
move to transfer
mark transfer robot occupancy active
unload package
on unload confirmed:
  buffer package at transfer
move to upstream transfer exit
on exit confirmed:
  release transfer robot occupancy
  release dropoff lease
release robot / mark task succeeded
```

Recommended downstream pickup order:

```text
request transfer pickup lease
move to transfer
mark transfer robot occupancy active
load package
on load confirmed:
  remove package from transfer buffer
move to downstream transfer exit
on exit confirmed:
  release transfer robot occupancy
  release pickup lease
move to destination
unload package
release robot / mark task succeeded
```

This fixes the current over-blocking case where downstream pickup can hold
transfer occupancy until the robot reaches the final destination.

### 9.6 Keep vacating, but make it local to the transfer region

Vacating is still necessary while transfer has robot capacity 1.

However, vacating should mean:

```text
robot is clear of the transfer conflict area
```

It should not mean:

```text
robot completed the entire remaining delivery
```

The exit waypoint should be close enough to transfer to prove clearance, but far
enough away that another robot can safely enter transfer.

### 9.7 Use watchdog polling only for reconciliation

A periodic loop can be useful, but it should not be the primary mechanism for
normal mission progression.

Use event-driven wakeups for normal behavior:

```text
package buffered
package removed
transfer occupancy released
lease released
robot reached staging
robot reached transfer exit
handling confirmed
```

Use low-frequency polling/watchdog checks for:

```text
stale command detection
lease timeout
robot state freshness
missed RMF completion
resource held too long
mission belief vs fleet-state reconciliation
```

This keeps the mission explainable while still protecting against missed events.
