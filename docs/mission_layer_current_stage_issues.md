# Mission Layer Current Stage Issues

This document records current mission-layer issues observed during test runs,
focused on the shared `transfer` zone and `staging` behavior in the two-robot
handoff mission.

The current architecture is still a valid centralized mission-control design.
The issues below are mostly about making shared-resource coordination more
explicit, better timed, and easier to explain.

## 1. Waiting at staging is implicit

The system can send a robot to `staging` when it requests `transfer` access and
the resource manager returns `WAIT`.

Current behavior:

```text
task requests transfer access
transfer cannot be granted
resource manager returns WAIT with staging waypoint
BT sends robot to staging
task becomes BLOCKED
task retries when the mission advances again
```

Observed cases:

- `robot2` waits at staging because the next package is not yet available at
  transfer.
- `robot2` waits at staging because `robot1` is still occupying transfer.
- `robot1` waits at staging because `robot2` is still using transfer.
- `robot1` waits at staging because transfer already contains one package and
  the transfer package capacity is full.

Issue:

```text
The mission state does not clearly explain why the robot is waiting, what is
blocking it, or what event will unblock it.
```

Recommended fix:

- add structured blocked reasons
- expose `waiting_at`, `blocked_by`, `unblock_condition`, and `next_expected_event`
- wake blocked tasks from specific package/resource/robot state changes
- make waiting policy configurable instead of treating `staging` as only a
  hardcoded waypoint

Useful blocked reasons:

```text
TRANSFER_ROBOT_OCCUPIED
TRANSFER_PACKAGE_FULL
PACKAGE_NOT_AVAILABLE
WAITING_FOR_TRANSFER_LEASE
WAITING_FOR_ROBOT_TO_EXIT_TRANSFER
WAITING_FOR_PACKAGE_PICKUP_CONFIRMATION
WAITING_FOR_PACKAGE_DROPOFF_CONFIRMATION
```

Example target state:

```text
robot1 is waiting at staging
reason: TRANSFER_PACKAGE_FULL
blocked by: robot2 transfer_to_destination
next expected event: robot2 loads package from transfer
```

## 2. Transfer ownership is mostly occupancy-based

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
The mission layer does not strongly model who owns the next right to enter
transfer, for what purpose, and in what order.
```

This makes coordination harder when both robots are near the transfer workflow:

- upstream robot wants to drop off a new package
- downstream robot wants to pick up an existing package
- one robot is still inside transfer
- transfer already has a buffered package
- a robot is waiting at staging

Recommended fix:

Split transfer control into:

```text
lease:
  robot has permission or intent to use transfer for pickup/dropoff

occupancy:
  robot is considered physically inside the transfer conflict area

package buffer:
  package is stored at transfer and occupies package capacity
```

The resource manager should grant a lease before a robot enters transfer.
Robot occupancy should only represent the robot being inside the transfer
conflict area. Package buffer state should represent package capacity.

This avoids using one field to mean scheduling intent, physical presence, and
package availability.

Suggested transfer model:

```text
transfer:
  robot_capacity = 1
  package_capacity = 1
  active_lease = robot / task / pickup_or_dropoff / package
  robot_occupancy = robot currently inside transfer
  package_buffer = package currently stored at transfer
  queue = waiting lease requests
```

## 3. Resource state changes are tied to BT ordering

Some transfer state changes happen only when the BT reaches later cleanup steps.
This can block the other robot longer than necessary or make package state
available later than expected.

Current sources of timing mismatch:

- transfer access grant immediately marks the resource occupied, before the
  robot physically reaches transfer
- downstream pickup can hold transfer occupancy until the robot reaches the
  final destination
- package buffer changes are tied to BT cleanup order instead of directly to
  load/unload confirmation
- robot clearance is logical, not independently detected from pose or region

Issue:

```text
The mission-layer transfer state may not match the physical handoff state closely
enough for efficient coordination.
```

Recommended fix:

Update transfer state according to the event that actually changes it.

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

For robot occupancy:

```text
on robot reaches transfer:
  mark transfer robot occupancy active

on robot confirmed clear of transfer:
  release transfer robot occupancy
  release transfer lease
```

Do not release transfer robot occupancy when a robot merely starts moving away.
Release it only after the robot is confirmed clear.

## 4. Clear-of-transfer and BT ordering

The current implementation considers a robot clear of transfer when the BT
releases the transfer resource. There is no independent physical check that the
robot is outside the transfer conflict area.

Issue: Transfer robot occupancy can be released too late or too broadly because it is controlled by task step ordering rather than explicit transfer clearance. This means sometimes the zone is only released when a robot is at ITS DESTINATION, which is later than expected

Recommended short-term fix:

Add explicit transfer exit waypoints:

```text
transfer_upstream_exit
transfer_downstream_exit
```

Then release transfer robot occupancy only after the robot reaches the relevant
exit waypoint. This gives the BT a concrete point where the robot is considered
clear of the transfer conflict area.

The BT should then make package state, robot occupancy, and lease state change
at the step that physically justifies the update.

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

Vacating is still necessary while `transfer.robot_capacity = 1`, but vacating
should mean:

```text
robot is clear of the transfer conflict area
```

It should not mean:

```text
robot completed the entire remaining delivery
```

Longer term, clear-of-transfer can be based on robot pose or footprint leaving a
transfer region, but exit waypoints are simpler and fit the current system.

## 5. Event-driven wakeups should be explicit

Blocked tasks currently retry when the mission manager advances through broad
events such as command completions, timers, or RMF/fleet callbacks.

Issue:

```text
A task waiting at staging is not woken by a specific resource or package event.
It is retried when some broader mission advancement happens.
```

Recommended fix:

Wake affected blocked tasks from explicit events:

```text
package buffered at transfer
package removed from transfer
transfer robot occupancy released
transfer lease released
robot reached staging
robot reached transfer exit
handling confirmed
```

Use low-frequency watchdog polling only for reconciliation:

```text
stale command detection
lease timeout
robot state freshness
missed RMF completion
resource held too long
mission belief vs fleet-state reconciliation
```

Normal mission progression should remain event-driven and explainable.

## 6. Summary of desired behavior

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
  transfer occupancy and lease are released
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
  transfer occupancy and lease are released
  robot2 continues to destination
```

The goal is to move from "robot tried transfer, got WAIT, moved to staging" to

```text
robot is waiting at staging because transfer/package state blocks its lease;
the mission layer knows what will unblock it and can explain that to the operator.
```
