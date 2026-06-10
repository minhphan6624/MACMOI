You are implementing an operator dashboard for a multi-robot delivery mission system built on top of ROS 2, Open-RMF/RMF-like task dispatching, and a custom mission layer.

The dashboard is for a single human operator supervising multiple robots during a collaborative delivery mission. The UI should be mission-oriented, not just robot-oriented. The operator should quickly understand:

1. What is the current mission doing?
2. Which robots are involved?
3. What step is currently active?
4. Is anything blocked, failed, delayed, or waiting?
5. What actions are available to the operator?

Implement the UI using mock data first. The frontend should be structured so that the mock data can later be replaced by a backend API or WebSocket stream without rewriting the UI.

Use clean component structure, typed data models, and readable code.

# Core layout

Create a dashboard layout with the following structure:

Top Bar
Main content area split into panels:

* Left column:

  * Mission Overview
  * Fleet Panel
* Right/main column:

  * Map View
  * Mission Timeline
  * Detail Panel
    Bottom section:
  * Alerts Panel
  * Event Log

Suggested layout:

┌──────────────────────────────────────────────────────────────┐
│ Top Bar, mission status, system status, main controls         │
├───────────────────────┬──────────────────────────────────────┤
│ Mission Overview      │ Map View                             │
│ Fleet Panel           │                                      │
├───────────────────────┼──────────────────────────────────────┤
│ Mission Timeline      │ Robot / Task Detail Panel            │
├───────────────────────┴──────────────────────────────────────┤
│ Alerts and Event Log                                          │
└──────────────────────────────────────────────────────────────┘

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

3. FleetPanel

---

Purpose:
Summarize every robot in the fleet.

Display a table or card list with:

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
* Keep the table compact and readable.

4. MapView

---

Purpose:
Show spatial information about robots, zones, and mission goals.

For the mock implementation, use a simple 2D schematic map, not a real map library unless the project already has one.

Display:

* A rectangular map area
* Robot markers positioned using position.x and position.y as percentages
* Zone markers for pickup, dropoff, transfer, and base zones
* Labels for robot IDs and zones
* Current active robot highlighted
* Current goal highlighted
* Transfer zone occupancy
* Optional line from active robot to current goal

Behavior:

* Clicking a robot marker selects the robot and updates DetailPanel.
* Clicking a zone can select the zone and update DetailPanel.
* Show occupied transfer zone distinctly.
* Keep the map simple and legible.

5. MissionTimeline

---

Purpose:
Show the mission as a sequence of dependent steps.

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
* Pending tasks should appear inactive but visible.
* Failed or waiting tasks should be easy to detect.
* Clicking a task selects it and updates DetailPanel.

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

7. AlertsPanel

---

Purpose:
Show issues requiring operator attention.

Display:

* Alert severity
* Source
* Message
* Timestamp
* Acknowledged status
* Related robot or task
* Action button, for example View or Acknowledge

Behavior:

* Critical alerts appear first, then warning, then info.
* Unacknowledged alerts appear before acknowledged alerts.
* Clicking an alert selects it and updates DetailPanel.
* Acknowledge button updates local mock state.

8. EventLog

---

Purpose:
Show recent mission, robot, task, alert, operator, and system events.

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
MapView.tsx
MissionTimeline.tsx
DetailPanel.tsx
AlertsPanel.tsx
EventLog.tsx
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
5. MapView shows robot markers, mission zones, transfer zone occupancy, and active robot.
6. MissionTimeline shows ordered mission steps and supports task selection.
7. DetailPanel changes based on selected robot, task, zone, or alert.
8. AlertsPanel prioritizes alerts and supports acknowledge/select actions.
9. EventLog shows timestamped events and updates when mock actions are triggered.
10. ScenarioSwitcher allows testing normal operation, transfer-zone conflict, low-battery risk, and robot failure.
11. The code uses clear TypeScript interfaces.
12. Mock data is centralized and easy to replace with live backend data.
13. Visual components are separated from mission logic and data loading.
14. The UI is readable and usable on a laptop screen.

Do not implement ROS 2, RMF, or backend API logic yet. Build the frontend dashboard with mock data and a clean data contract so that it can later connect to the mission layer.
