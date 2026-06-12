# Mission Layer Current Stage Issues

This document records the current state of the mission-layer integration and
the issues that still matter for physical two-robot tests.

The current architecture remains a centralized mission-control design:

```text
mission_manager owns collaboration logic
Open-RMF / free_fleet execute traffic-aware movement
Nav2 executes robot-local navigation
```

The active mission is still:

```text
source -> transfer -> destination

tb3_1: source -> transfer
tb3_2: transfer -> destination
```

---

## 1. Resolved Direction: No Shared Staging Resource

The earlier design used one shared `staging` waypoint for both robots. That
created a second coordination problem: both robots could target the same wait
pose before the transfer-zone behavior was stable.

The current design uses directional wait/clear points instead:

```text
tb3_1 waits or clears at upstream_exit
tb3_2 waits or clears at downstream_exit
```

Only `transfer` is a managed mission resource.

This keeps the collaboration constraint focused on the handoff:

```text
transfer.robot_capacity = 1
transfer.package_capacity = 1
transfer.active_lease = one robot/task/purpose/package
```

The old `staging` waypoint may still exist in map assets, but it is not part of
the active mission logic.

---

## 2. Current RMF Graph Shape

The current RMF graph is intentionally narrow:

```text
robot1_home <-> source
source <-> upstream_exit
upstream_exit <-> transfer      mutex: transfer_zone
transfer <-> downstream_exit    mutex: transfer_zone
downstream_exit <-> destination
destination <-> robot2_home
```

The `transfer_zone` mutex should remain only on the lanes that enter or leave
the transfer conflict area:

```text
upstream_exit <-> transfer
transfer <-> downstream_exit
```

Avoid adding direct lanes such as:

```text
source <-> transfer
transfer <-> destination
```

unless the mission semantics are changed. Direct transfer lanes can bypass the
directional wait/clear points and make the physical route contradict the mission
resource model.

---

## 3. Transfer Ownership Is Lease-Based But Still Simple

The transfer zone now separates:

```text
active_lease:
  robot has permission or intent to use transfer for pickup/dropoff

robot_occupancy:
  robot is considered inside the transfer conflict area

package_occupancy:
  package is buffered at transfer and occupies package capacity
```

Current limitations:

- there is no ordered transfer queue
- there are no lease timeouts
- there is no operator force-release action
- stale leases still need explicit recovery handling

Recommended next improvement:

```text
add a small queue and timeout model to ResourceManager
```

This is not required for the two-robot happy path, but it will matter for
failure and recovery behavior.

---

## 4. Resource State Changes Are Better Timed, But Still Logical

The BT now changes transfer state closer to the relevant physical event:

```text
upstream unload:
  buffer package at transfer

downstream load:
  remove package from transfer buffer

robot reaches upstream_exit/downstream_exit:
  release transfer occupancy and active lease
```

This fixes the previous over-blocking case where a robot could hold transfer
until the end of a downstream delivery.

Remaining limitation:

```text
clear-of-transfer is based on reaching a waypoint, not on continuous footprint
or region detection.
```

That is acceptable for the current lab mission, but a richer system should
eventually detect whether a robot has physically cleared the transfer region.

---

## 5. Movement Completion Has Multiple Paths

The current system has three movement completion paths.

Primary direct path:

```text
mission_manager publishes mission_execution_commands
free_fleet Nav2 adapter attaches that command context
Nav2 reports goal succeeded
free_fleet Nav2 adapter publishes mission_execution_results
mission_manager completes the command
```

Secondary completion path:

```text
task_summaries:
  RMF reports STATE_COMPLETED for the tracked RMF task
```

This was added because physical tests showed cases where Nav2 reached a goal
but the mission did not immediately advance from the RMF task-summary path.

Relevant expected logs:

```text
Published mission execution result: ...
Mission command completed from nav2_result: cmd_X
Mission command completed from task_summary: cmd_X
```

Remaining limitation:

```text
the direct path uses a mission command context side channel
```

This is pragmatic for testing. A cleaner long-term adapter should carry command
context through a more formal execution interface.

---

## 6. Event-Driven Wakeups Are Still A Weak Area

Blocked tasks currently retry when the mission manager advances through broad
events:

```text
movement command completed
handling timer completed
RMF task summary received
direct execution result received
```

This works for the current happy path, but it is still not a formal event model.

Recommended improvement:

```text
wake blocked tasks from explicit world/resource events:
  package buffered at transfer
  package removed from transfer
  transfer occupancy released
  lease released
  robot reached directional wait point
```

A low-frequency watchdog tick may still be useful for reconciliation, but normal
mission progress should remain explainable through events.

---

## 7. Package Handling Is Simulated

Load/unload is still represented by a ROS timer:

```text
HANDLE_ITEM -> 5 second timer -> command succeeded
```

This is acceptable for current mission-layer testing, but not a final physical
handoff confirmation model.

Future confirmation sources:

- robot-side actuator result
- sensor package detection
- simulation truth state
- operator confirmation
- fiducial or marker detection

The UI should clearly distinguish simulated handling from confirmed physical
handling once operator-facing workflows matter.

---

## 8. Summary Of Current Desired Behavior

For upstream dropoff:

```text
tb3_1 loads package at source
tb3_1 requests transfer dropoff lease
if transfer is unavailable:
  tb3_1 waits at upstream_exit with an explicit blocked reason
when transfer is available:
  tb3_1 enters transfer
  tb3_1 unloads package
  package is buffered at transfer
  tb3_1 exits to upstream_exit
  transfer occupancy and lease are released
```

For downstream pickup:

```text
tb3_2 requests transfer pickup lease
if package is unavailable or transfer is occupied:
  tb3_2 waits at downstream_exit with an explicit blocked reason
when package and transfer are available:
  tb3_2 enters transfer
  tb3_2 loads package
  package is removed from transfer buffer
  tb3_2 exits to downstream_exit
  transfer occupancy and lease are released
  tb3_2 continues to destination
```

The target behavior is:

```text
robots wait on their own side of transfer
transfer is the only shared mission resource
the mission layer explains why a robot is waiting
movement completion advances the BT promptly
```
