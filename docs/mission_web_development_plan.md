# Mission Web/API Development Plan

This document captures the planned web-facing work for the mission layer. It should be used after the ROS mission node has been validated against a live RMF deployment.

The web layer should expose and visualize the batch mission view. It should not replace the existing RMF fleet dashboard.

---

## 1. Expose Mission State

Add a mission-state serialization layer that can return:

```text
mission status
total packages
delivered count
remaining count
package statuses
robot statuses
robot logical locations
active package/task IDs
transfer robot occupancy
transfer package buffer
waiting robot/package at staging
recent mission events/actions
```

This should be implemented close to the mission core so both tests and the future API can use the same state shape.

---

## 2. Add Mission API Backend

Add backend endpoints for mission control:

```text
POST /missions
POST /missions/{mission_id}/start
POST /missions/{mission_id}/pause
POST /missions/{mission_id}/resume
POST /missions/{mission_id}/abort
GET  /missions/{mission_id}
```

The backend can either:

```text
run the MissionManager in-process
```

or:

```text
communicate with the ROS mission manager node
```

For the current project, prefer keeping one mission authority. If the ROS node owns the live mission, the API backend should observe/control that node rather than creating a separate mission manager instance.

---

## 3. Add Live Updates

The UI should not rely only on manual refresh. Add either:

```text
WebSocket updates
Server-Sent Events
short polling
```

The live stream should include mission state changes, recent events, emitted actions, RMF task IDs, and rejected-task/failure messages.

---

## 4. Add rmf-web Mission Tab

The mission tab should answer five operator questions from the design document:

```text
What is the mission doing right now?
What is happening at the transfer zone?
What are the robots currently doing?
How far through the package batch are we?
Can the operator intervene?
```

The proof-of-concept layout should use four compact operational panels plus controls:

```text
Mission summary:
  mission ID
  mission state
  total package count
  delivered count
  remaining count
  progress indicator

Transfer zone:
  robot occupancy
  package buffer occupancy
  waiting robot/package
  transfer status: free, blocked, or in use

Robot activity:
  Robot 1 status/location/current leg/current package
  Robot 2 status/location/current leg/current package
  links to the existing RMF robots/tasks views for lower-level detail

Event timeline:
  package loaded/dropped/picked/delivered
  robot staged/entered transfer
  mission paused/resumed/aborted/completed
  recent RMF task request/response status for debugging
```

Controls:

```text
create mission
start
pause
resume
abort
```

The mission tab should not become:

```text
a replacement for the full RMF fleet dashboard
a debugging console for every ROS topic
a manual robot navigation panel
```

It should sit above the existing RMF dashboard and present batch mission progress, transfer bottleneck state, and operator controls.

---

## 5. Add Debug Visibility

Before polishing the UI, expose enough detail to validate behavior:

```text
last emitted action
last consumed event
active RMF task IDs
handling timer currently running
current package assigned to each robot
current transfer occupancy/buffer state
```

This is important because the mission layer currently has no dedicated UI and only minimal ROS logs.
