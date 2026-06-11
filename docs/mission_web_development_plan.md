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
run the mission runtime in-process
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

---

## 6. Future: Persistent Run Records, Rosbags, and AI-Ready Exports

The current RMF web API already has a database layer for operational entities
such as task states, task logs, alerts, and scheduled tasks. For a lab system,
that storage should be treated as the start of a broader experiment record, not
as a replacement for live ROS/RMF state.

The live dashboard should continue to observe live RMF/ROS updates. Persistent
storage should be used for history, audit, artifact tracking, and later offline
analysis.

Suggested responsibilities:

```text
database:
  mission/run metadata
  task history
  alert history
  operator actions
  artifact metadata

filesystem or object storage:
  rosbag files
  compressed ROS logs
  exported JSON bundles
  screenshots or reports

API server:
  list/search run records
  start/stop recording requests
  expose artifact download endpoints
  build export bundles for later analysis
```

Avoid storing large rosbag binaries directly in the SQL database. Store the file
path, size, checksum, topic list, time range, and related mission/run ID in the
database, while keeping the bag files on disk or object storage.

Possible future backend shape:

```text
mission_run:
  id
  mission_id
  started_at
  ended_at
  status
  map_name
  robot_names
  software_commit
  notes

artifact:
  id
  run_id
  type: rosbag | ros_log | api_log | mission_export | screenshot
  path
  size_bytes
  sha256
  topics
  start_time
  end_time
  created_at
```

Possible API endpoints:

```text
GET  /runs
GET  /runs/{run_id}
GET  /runs/{run_id}/artifacts
GET  /artifacts/{artifact_id}/download
POST /recordings/start
POST /recordings/stop
POST /runs/{run_id}/export
```

For AI-agent processing, prefer a self-contained export bundle rather than a
raw database dump:

```text
run_manifest.json
mission_state_timeline.json
task_states.json
alerts.json
operator_actions.json
rosbag/
logs/
```

A practical first implementation step is to move the API server away from the
default in-memory SQLite configuration, confirm task states and logs survive a
restart, then add `mission_run` and `artifact` records before adding rosbag
recording controls.
