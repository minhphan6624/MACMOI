# Mission Layer Extension Roadmap

This document records how the v1 mission layer can evolve if the mission becomes more general or complex.

The v1 mission is intentionally fixed:

```text
Robot 1: source A -> transfer B
Robot 2: transfer B -> destination C
one transfer zone
one package buffer
fixed robot roles
simple rule evaluator
RMF patrol/loop-style waypoint tasks
```

That setup is suitable for the first implementation. It should not be over-generalized too early. The goal is to keep the v1 system working, deterministic, and easy to debug.

---

## 1. Architectural Backbone To Keep

The main architecture should remain event-driven:

```text
RMF / robots
        ↓
RMF bridge
        ↓
mission events
        ↓
Mission manager
        ↓
mission actions
        ↓
RMF tasks
```

RMF should continue to own:

* robot execution
* traffic coordination
* task execution state
* fleet/task updates

The mission layer should continue to own:

* mission lifecycle
* package state
* transfer/resource rules
* dispatch timing
* operator-facing mission state

The UI should display mission state and may also display lower-level RMF/debug events, but it should not become the source of mission truth.

---

## 2. Raw Events vs Mission Events

As the system becomes more complex, there may be more low-level events:

* task phase changed
* task completed
* robot reached waypoint
* robot became idle
* robot entered a zone
* load confirmed
* unload confirmed
* robot pose updated
* fleet state changed

These should be collected by the RMF bridge or a lower-level event layer.

The mission manager should receive a smaller set of mission-level facts:

* package moved to a new mission state
* robot became available for mission work
* transfer entry was granted
* leg completed
* mission was paused, resumed, or aborted

This split keeps the mission state machine stable. Low-level observations can change without forcing the mission manager to understand every RMF or robot detail.

Recommended structure:

```text
RMF task/fleet updates
        ↓
RMF bridge
        ├── raw event log / debug stream
        ↓
mission event translation
        ↓
Mission manager
        ↓
mission state + mission timeline
```

---

## 3. First Generalization: Configuration

The first extension should not be a new planner. It should make v1 names and roles configurable.

Move hardcoded values into config:

```python
robots = {
    "tb3_1": {
        "role": "upstream",
        "home": "wp1",
    },
    "tb3_2": {
        "role": "downstream",
        "home": "wp2",
    },
}

zones = {
    "A": {"type": "source", "waypoint": "wp_source"},
    "X": {"type": "staging", "waypoint": "wp_staging"},
    "B": {"type": "transfer", "waypoint": "wp_transfer"},
    "C": {"type": "destination", "waypoint": "wp_destination"},
}
```

This keeps the logic simple while allowing robot names, waypoint names, and zone names to change without editing mission code.

---

## 4. Robot Role Generalization

V1 assumes:

```text
tb3_1 = upstream robot
tb3_2 = downstream robot
```

Later versions may need multiple eligible robots. At that point, the mission manager should stop asking:

```text
Is Robot 1 idle?
```

and start asking:

```text
Which eligible robot can perform the next leg?
```

A more general robot model:

```python
class RobotRecord:
    robot_id: str
    status: RobotStatus
    home_waypoint: str
    capabilities: set[str]
    assigned_leg_id: str | None
```

Example capabilities:

```text
carry_package
upstream_route
downstream_route
can_enter_zone_B
```

For small extensions, fixed roles can remain. For larger extensions, roles should become capabilities.

---

## 5. Transfer Zone Generalization

V1 uses one transfer state:

```python
class TransferZoneState:
    robot_occupancy: Optional[str]
    package_buffer: Optional[str]
    waiting_robot: Optional[str]
```

For multiple zones or larger capacity, replace this with a generic resource model:

```python
class ResourceState:
    resource_id: str
    resource_type: str  # transfer_zone, staging_zone, loading_area
    robot_capacity: int
    package_capacity: int
    occupied_by_robots: list[str]
    buffered_packages: list[str]
    waiting_queue: list[str]
```

Then Zone B is not special. It is one resource with:

```text
robot_capacity = 1
package_capacity = 1
```

Other transfer zones could have different capacities or rules.

---

## 6. Package Flow Generalization

V1 package state is linear:

```text
AT_SOURCE
INBOUND_TO_TRANSFER
AT_TRANSFER
INBOUND_TO_DESTINATION
DELIVERED
```

This is enough for A -> B -> C. For more zones or routes, package state should be represented as location plus active leg:

```python
class PackageRecord:
    package_id: str
    current_location: str
    destination: str
    assigned_robot: str | None
    active_leg_id: str | None
    status: PackageStatus
```

Movement should be represented as mission legs:

```python
class MissionLeg:
    leg_id: str
    package_id: str
    from_zone: str
    to_zone: str
    assigned_robot: str | None
    required_resource_ids: list[str]
    state: LegState
```

This changes the model from:

```text
package advances through a fixed enum
```

to:

```text
package moves through a graph of zones
```

That is the key step toward general missions.

---

## 7. Rule Evaluator Evolution

V1 can use direct rules:

```text
IF Robot 1 is idle
AND packages remain
AND transfer buffer is free
THEN dispatch upstream task
```

This is fine while the mission is fixed.

As complexity grows, possible approaches are:

```text
Small expansion:
  configurable rule evaluator

Medium complexity:
  workflow/state-machine engine

High concurrency/shared-resource complexity:
  Petri net or token-based model

Robot behavior/fallback complexity:
  behavior tree
```

For this project, Petri nets may become useful if the hard problem becomes package flow through capacity-constrained places:

```text
source packages -> upstream robot -> transfer buffer -> downstream robot -> destination
```

That maps naturally to:

* tokens: packages or robot/resource availability
* places: source, robot carrying, transfer buffer, destination
* transitions: load, move, unload, pickup, deliver
* capacity limits: transfer zone and package buffer

Behavior trees are more useful if the problem becomes robot behavior selection and recovery, such as retries, fallback navigation, or controller switching.

---

## 8. Task Planning Evolution

V1 mission actions can directly dispatch waypoint task segments:

```text
dispatch_to_source
dispatch_to_staging
dispatch_into_transfer
dispatch_to_destination
send_robot_home
```

Later, the mission layer may need to plan a route through several zones:

```text
Mission goal:
  deliver P7 from A to D

Planner result:
  A -> B by tb3_1
  B -> C by tb3_3
  C -> D by tb3_2
```

At that point, the mission manager should create legs first, then dispatch RMF task segments for those legs.

The RMF bridge should still hide RMF-specific task formatting from the mission planner.

---

## 9. Suggested Evolution Path

Do not jump from v1 directly to a fully generic planner.

Recommended path:

```text
v1:
  fixed two-robot A-B-C mission

v1.5:
  configurable robot names, waypoint names, source, transfer, destination

v2:
  N robots, still fixed route pattern, simple deterministic rules

v2.5:
  multiple transfer zones/resources with capacities

v3:
  generic zone/resource graph and mission legs

v4:
  formal model such as Petri net/workflow engine if concurrency becomes hard to reason about
```

This keeps each step testable.

---

## 10. Practical Design Rule

The mission layer should become more general only when the mission requires it.

For v1, keep:

* fixed roles
* one transfer zone
* simple package states
* direct rule evaluation
* patrol/loop-style RMF task segments

But isolate the parts likely to change:

* robot names and roles
* zone and waypoint names
* RMF task dispatch mapping
* transfer/resource rules
* mission state transition logic

This gives the current implementation a clear path to grow without making the first implementation unnecessarily complex.
