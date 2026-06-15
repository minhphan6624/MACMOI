You are implementing an operator dashboard for a multi-robot delivery mission system built on top of ROS 2, Open-RMF/RMF-like task dispatching, and a custom mission layer.

The dashboard is for a single human operator supervising multiple robots during a collaborative delivery mission. The UI should be mission-oriented, not just robot-oriented. The operator should quickly understand:

1. What is the current mission doing?
2. Which robots are involved?
3. What step is currently active?
4. Is anything blocked, failed, delayed, or waiting?
5. What actions are available to the operator?

Implement the UI using mock data first. The frontend should be structured so that the mock data can later be replaced by a backend API or WebSocket stream without rewriting the UI.

Use clean component structure, typed data models, and readable code.

# Current implementation status

The initial mock Mission dashboard has been connected to the mission web/API
bridge and then reorganized toward a flow-first operator interface.

Implemented web/API integration:

```text
API server:
  subscribes to mission_state, mission_debug_state, mission_events
  exposes /missions/current/state
  exposes /missions/current/debug_state
  exposes Socket.IO rooms for state, debug_state, and events

API client / dashboard framework:
  exposes missionStateObs
  exposes missionDebugStateObs
  exposes missionEventsObs

Mission dashboard:
  starts from mock scenario data
  overlays live mission_state when available
  appends mission_events into the activity/event stream
```

Implemented UI reorganization:

```text
MissionFlowView:
  replaces the synthetic MapView in the Mission tab's primary panel
  shows Source -> Transfer -> Destination mission semantics
  shows package chips, active legs, transfer status, blocker, and next step
  links to the real Open-RMF Map tab for spatial inspection

ActivityPanel:
  combines Events and Alerts into a tabbed panel

FleetPanel:
  changed from a wide table to mission-relevant robot cards

MissionTimeline:
  renamed visually to Mission Steps
  groups package-like steps by P1/P2/etc. when task IDs or labels include package IDs

TopBar:
  scenario selector is labelled Demo Scenario because it is a no-lab fallback tool
```

The current `MissionFlowView` is an intentionally simple first draft. It should
be improved as the mission model grows, but it is the preferred direction over a
fake mission-local map.

# Updated product direction

The Mission tab should be the operator's coordination surface. It should answer:

```text
What is moving?
What is waiting?
What is blocked?
Who owns the next action?
Where should the operator click to inspect or intervene?
```

The Mission tab should not duplicate the full Open-RMF Map tab. The split is:

```text
Mission tab:
  mission intent, package flow, transfer/resource state, task ownership, blockers

Map tab:
  building map, robot pose, lanes, trajectories, doors/lifts, spatial inspection

Robots tab:
  fleet health, online/offline state, battery, robot diagnostics

Tasks tab:
  RMF task lifecycle and task-level controls
```

If a Mission-tab panel needs map context, it should link to or focus the real
Map tab using robot IDs, task IDs, waypoint/place IDs, or resource IDs. The
custom `mission_state` should not carry fake x/y map coordinates just to render
a local map-like panel.

# Core layout

Create a dashboard layout with the following structure:

Top Bar
Main content area split into panels:

* Left column:

  * Mission Overview
  * Robots / mission-relevant fleet cards
* Center/main column:

  * Mission Flow
  * Mission Steps
* Right column:

  * Detail Panel
  * Activity Panel with Events and Alerts tabs


The layout should be usable on a standard laptop screen. Prioritize clarity over visual complexity.

# Data model

Create TypeScript interfaces/types for this dashboard state.

Use this structure as the initial mock data contract:

{
"mission": {
"id": "delivery_001",
"name": "Multi-Point Delivery Mission",
"status": "active",
"phase": "moving_to_pickup",
"current_step": 2,
"total_steps": 7,
"active_robot": "tb3_01",
"current_blocker": null,
"next_step": "pickup_item",
"started_at": "10:35:12",
"last_update": "10:42:18"
},
"system": {
"connection_status": "connected",
"robots_online": 2,
"robots_total": 3,
"last_update": "10:42:18"
},
"robots": [
{
"id": "tb3_01",
"label": "Robot 1",
"state": "moving",
"task": "pickup_A",
"battery": 82,
"location": "corridor_1",
"position": { "x": 35, "y": 45 },
"issue": null,
"rmf_task_id": "rmf_task_001",
"last_update": "10:42:18"
},
{
"id": "tb3_02",
"label": "Robot 2",
"state": "waiting",
"task": "transfer_B",
"battery": 64,
"location": "staging_zone",
"position": { "x": 62, "y": 55 },
"issue": "Waiting for transfer zone",
"rmf_task_id": "rmf_task_002",
"last_update": "10:42:15"
},
{
"id": "tb3_03",
"label": "Robot 3",
"state": "idle",
"task": null,
"battery": 91,
"location": "base",
"position": { "x": 15, "y": 80 },
"issue": null,
"rmf_task_id": null,
"last_update": "10:42:10"
}
],
"tasks": [
{
"id": "assign_robot",
"label": "Assign robot",
"status": "completed",
"assigned_robot": "tb3_01",
"start": null,
"goal": null,
"dependencies": [],
"notes": ""
},
{
"id": "move_to_pickup",
"label": "Move to pickup",
"status": "active",
"assigned_robot": "tb3_01",
"start": "base",
"goal": "pickup_zone_A",
"dependencies": [],
"notes": ""
},
{
"id": "pickup_item",
"label": "Pickup item",
"status": "pending",
"assigned_robot": "tb3_01",
"start": "pickup_zone_A",
"goal": null,
"dependencies": ["move_to_pickup"],
"notes": ""
},
{
"id": "move_to_transfer",
"label": "Move to transfer zone",
"status": "pending",
"assigned_robot": "tb3_01",
"start": "pickup_zone_A",
"goal": "transfer_zone",
"dependencies": ["pickup_item"],
"notes": "Transfer zone must be free"
},
{
"id": "handoff",
"label": "Handoff / transfer",
"status": "pending",
"assigned_robot": "tb3_01, tb3_02",
"start": "transfer_zone",
"goal": null,
"dependencies": ["move_to_transfer"],
"notes": "Requires both robots and free transfer zone"
},
{
"id": "move_to_dropoff",
"label": "Move to dropoff",
"status": "pending",
"assigned_robot": "tb3_02",
"start": "transfer_zone",
"goal": "dropoff_zone_B",
"dependencies": ["handoff"],
"notes": ""
},
{
"id": "complete_delivery",
"label": "Complete delivery",
"status": "pending",
"assigned_robot": "tb3_02",
"start": "dropoff_zone_B",
"goal": null,
"dependencies": ["move_to_dropoff"],
"notes": ""
}
],
"zones": [
{
"id": "pickup_zone_A",
"label": "Pickup A",
"type": "pickup",
"position": { "x": 78, "y": 22 },
"status": "available"
},
{
"id": "transfer_zone",
"label": "Transfer Zone",
"type": "transfer",
"position": { "x": 55, "y": 48 },
"status": "occupied",
"occupied_by": "tb3_02"
},
{
"id": "dropoff_zone_B",
"label": "Dropoff B",
"type": "dropoff",
"position": { "x": 82, "y": 75 },
"status": "available"
},
{
"id": "base",
"label": "Base",
"type": "base",
"position": { "x": 15, "y": 80 },
"status": "available"
}
],
"alerts": [
{
"id": "alert_001",
"severity": "warning",
"source": "mission",
"message": "Transfer zone is currently occupied by tb3_02",
"timestamp": "10:42:10",
"acknowledged": false,
"related_robot": "tb3_02",
"related_task": "handoff"
},
{
"id": "alert_002",
"severity": "info",
"source": "robot",
"message": "tb3_02 is waiting at staging zone",
"timestamp": "10:41:40",
"acknowledged": false,
"related_robot": "tb3_02",
"related_task": "transfer_B"
}
],
"events": [
{
"id": "event_001",
"timestamp": "10:35:12",
"type": "mission_event",
"message": "Mission delivery_001 started"
},
{
"id": "event_002",
"timestamp": "10:35:18",
"type": "task_event",
"message": "tb3_01 assigned to pickup_A"
},
{
"id": "event_003",
"timestamp": "10:36:03",
"type": "robot_event",
"message": "tb3_01 started moving to pickup_zone_A"
},
{
"id": "event_004",
"timestamp": "10:38:10",
"type": "task_event",
"message": "tb3_02 assigned to staging_zone"
},
{
"id": "event_005",
"timestamp": "10:42:10",
"type": "alert_event",
"message": "Transfer zone occupied by tb3_02"
}
]
}

# Supported enum values

Mission status:

* idle
* active
* paused
* completed
* failed
* cancelled

Mission phase:

* idle
* mission_created
* robot_assigned
* moving_to_pickup
* pickup_reached
* loading
* moving_to_transfer_zone
* waiting_at_transfer_zone
* transfer_complete
* moving_to_dropoff
* dropoff_reached
* mission_complete
* mission_failed
* mission_paused

Robot state:

* idle
* assigned
* moving
* waiting
* blocked
* charging
* failed
* offline

Task status:

* pending
* active
* completed
* waiting
* failed
* skipped
* cancelled

Alert severity:

* critical
* warning
* info

Zone type:

* pickup
* dropoff
* transfer
* base
* staging
* blocked

# Component requirements

1. TopBar

---

Purpose:
Show global mission and system state.

Display:

* Mission name or ID
* Mission status
* System connection status
* Online robots count, for example "2 / 3 robots online"
* Last update time
* Main controls:

  * Start Mission
  * Pause Mission
  * Resume Mission
  * Cancel Mission

Behavior:

* Show Pause only when mission is active.
* Show Resume only when mission is paused.
* Show Start when mission is idle, completed, failed, or cancelled.
* Cancel should be visible during active or paused missions.
* For now, button clicks can log actions to console and append an operator event to the mock event log.
* Destructive actions such as Cancel Mission should ask for confirmation.

2. MissionOverview

---

Purpose:
Give the operator a concise summary of the active mission.

Display:

* Mission status
* Current phase, formatted as readable text
* Progress, for example "2 / 7 steps"
* Active robot
* Current blocker, show "None" when null
* Next step
* Started at
* Last update

Behavior:

* Highlight the current mission phase.
* If current_blocker is not null, show it prominently.
* If mission status is failed, show failed state prominently.
* If mission status is completed, show completion state clearly.

3. Robots / FleetPanel

---

Purpose:
Summarize the mission-relevant robots first. For the current handoff mission,
this is normally `tb3_1` and `tb3_2`. The full fleet-wide view should remain in
the Open-RMF Robots tab.

Display compact robot cards with:

* Robot ID or label
* State
* Current task
* Battery percentage
* Location
* Issue

Behavior:

* Clicking a robot selects it and updates the DetailPanel.
* Visually distinguish problematic states:

  * waiting
  * blocked
  * failed
  * offline
  * low battery
* Define low battery as battery below 25%.
* Keep the cards compact and readable.
* Do not make the Mission tab the full fleet-management table.

4. MissionFlowView

---

Purpose:
Show mission semantics, not physical map truth.

For the current two-robot handoff mission, the flow should represent:

Display:

* Source / pickup queue
* Source-to-transfer leg
* Transfer zone / buffer
* Transfer-to-destination leg
* Destination / dropoff queue
* Packages at each mission stage
* Active package/task/robot
* Transfer availability, occupancy, buffered package, and waiting reason
* Current blocker and next expected action
* Link or button to open the real Open-RMF Map tab

Behavior:

* Clicking a mission task selects it and updates DetailPanel.
* Clicking a zone/resource selects it and updates DetailPanel.
* Active work should be visually dominant.
* Normal background state should be summarized.
* Blocked, waiting, failed, delayed, or operator-required state should be expanded or visually prominent.
* The panel should not imply real robot pose, real map coordinates, or RMF route geometry unless it is backed by RMF map/fleet data.

Near-term target:

```text
Source
  waiting: P2, P3
  active pickup: P1

tb3_1 source -> transfer
  active, waiting, blocked, or completed

Transfer
  available / occupied / blocked
  buffer: P1 or none

tb3_2 transfer -> destination
  active, waiting, blocked, or completed

Destination
  delivered: 0 / 3
```

Larger-mission target:

```text
Source A        Source B
waiting: 4      waiting: 2
active: P7      active: P11

Transfer resources
queue: P2, P5, P8
blocked: P5 waiting 4m

Destinations
delivered: 13 / 20
late: 2
```

5. MissionSteps / MissionTimeline

---

Purpose:
Show the mission as dependent work, grouped by package or mission stage when
possible.

Display each task/step with:

* Step label
* Status
* Assigned robot
* Start location
* Goal location
* Dependencies
* Notes

Behavior:

* The active task should be visually prominent.
* Completed tasks should appear complete.
* Pending tasks should be visible but should not dominate the page when there are many of them.
* Failed or waiting tasks should be easy to detect.
* Clicking a task selects it and updates DetailPanel.
* Package-like tasks should be grouped by package ID, for example P1, P2, P3.
* Future versions should allow completed/normal work to collapse while blocked or waiting work remains expanded.

6. DetailPanel

---

Purpose:
Show details for the selected robot, task, zone, or alert.

Default state:

* If nothing is selected, show a brief summary of the active mission and instructions such as "Select a robot, task, zone, or alert to inspect details."

Robot detail view:
Show:

* Robot ID
* Label
* State
* Current task
* RMF task ID
* Battery
* Location
* Position
* Issue
* Last update
* Recent events related to that robot
* Available actions:

  * Send to charger
  * Pause robot
  * Retry current task
  * Reassign task

Task detail view:
Show:

* Task ID
* Label
* Status
* Assigned robot
* Start
* Goal
* Dependencies
* Notes
* Related alerts
* Available actions:

  * Retry task
  * Reassign task
  * Cancel task

Zone detail view:
Show:

* Zone ID
* Label
* Type
* Status
* Occupied by, when available
* Related robots nearby, if possible

Alert detail view:
Show:

* Severity
* Source
* Message
* Timestamp
* Related robot
* Related task
* Acknowledge button

Behavior:

* Detail action buttons can initially log to console and append mock operator events.
* Acknowledge alert should update the mock alert state.

7. ActivityPanel / Alerts

---

Purpose:
Show recent mission activity and issues requiring operator attention.

Display Events tab:

* Timestamp
* Event type
* Message

Display Alerts tab:

* Alert severity
* Source
* Message
* Timestamp
* Acknowledged status
* Related robot or task
* Action button, for example View or Acknowledge

Behavior:

* Events and alerts can share one Activity panel to save first-viewport space.
* Critical alerts appear first, then warning, then info.
* Unacknowledged alerts appear before acknowledged alerts.
* Clicking an alert selects it and updates DetailPanel.
* Acknowledge button updates local mock state.

8. EventLog

---

Purpose:
Show recent mission, robot, task, alert, operator, and system events. This is
currently folded into ActivityPanel on the Mission tab.

Display:

* Timestamp
* Event type
* Message

Behavior:

* Newest events should be visible, either sorted descending or with auto-scroll if sorted ascending.
* Include event type labels.
* Operator actions from button clicks should append new events.
* Keep the log readable and compact.

# State management

Implement local frontend state for:

* dashboardData
* selectedEntity, with type and id
* acknowledged alerts
* event log updates caused by mock operator actions

Recommended selectedEntity shape:

{
"type": "robot" | "task" | "zone" | "alert" | "mission" | null,
"id": string | null
}

Create helper functions:

* selectRobot(robotId)
* selectTask(taskId)
* selectZone(zoneId)
* selectAlert(alertId)
* acknowledgeAlert(alertId)
* appendEvent(type, message)
* handleMissionAction(action)
* handleRobotAction(robotId, action)
* handleTaskAction(taskId, action)

# Mock scenarios

Add a way to switch between at least four mock scenarios:

1. Normal active mission

* Mission active
* One robot moving
* No major blocker

2. Transfer zone occupied

* Mission waiting
* Transfer zone occupied
* One robot waiting at staging zone
* Warning alert visible

3. Low battery risk

* One active robot below 25% battery
* Warning alert visible
* Suggested operator actions available in DetailPanel

4. Robot failure

* One robot failed or offline during active task
* Critical alert visible
* Mission status failed or blocked
* Retry and reassign actions visible

The scenario switcher can be a simple dropdown in the TopBar or a developer panel.

# Implementation details

Use a clean folder structure, for example:

src/
components/
TopBar.tsx
MissionOverview.tsx
FleetPanel.tsx
MissionFlowView.tsx
MissionSteps.tsx
DetailPanel.tsx
ActivityPanel.tsx
ScenarioSwitcher.tsx
data/
mockDashboardData.ts
types/
dashboard.ts
utils/
formatting.ts
selectors.ts
App.tsx

Use TypeScript types for all props.

Use readable UI styling. Prefer a simple, professional operations-dashboard look:

* Clear panels/cards
* Compact spacing
* Strong hierarchy
* Status badges
* Tables where appropriate
* No unnecessary animation
* No overly decorative visuals

Make sure the interface works with the mock data first.

# Backend integration preparation

Do not hard-code business logic inside visual components.

Create a single data loading boundary so that later the mock data can be replaced by:

* REST API polling, or
* WebSocket mission state updates

Create a function or hook such as:

useDashboardData()

For now, useDashboardData() can return mock state and local update functions. Later it should be replaceable with live backend data.

# Acceptance criteria

The implementation is complete when:

1. The dashboard renders all major panels.
2. The TopBar shows mission and system state.
3. MissionOverview clearly shows mission phase, progress, active robot, blocker, and next step.
4. FleetPanel lists all robots and supports robot selection.
5. MissionFlowView shows source, transfer, destination, active legs, package stage, transfer status, blocker, and next action.
6. MissionSteps shows ordered or grouped mission steps and supports task selection.
7. DetailPanel changes based on selected robot, task, zone, or alert.
8. ActivityPanel prioritizes alerts and supports acknowledge/select actions.
9. ActivityPanel/EventLog shows timestamped events and updates when mock actions are triggered.
10. ScenarioSwitcher allows testing normal operation, transfer-zone conflict, low-battery risk, and robot failure.
11. The code uses clear TypeScript interfaces.
12. Mock data is centralized and easy to replace with live backend data.
13. Visual components are separated from mission logic and data loading.
14. The UI is readable and usable on a laptop screen.

The first version used mock data. The current branch has begun the live
connection through the API server and mission topics. Continue to keep visual
components separate from business logic and data loading so the UI can evolve
without rewriting the mission manager.
