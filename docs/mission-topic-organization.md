# Mission Topic Organization

This document records how mission-layer ROS topics should be organized so the
web UI, execution bridge, RMF integration, and developer debugging do not depend
on the same oversized state payload.

## Current Published Topics

`task_api_requests`

Type: `rmf_task_msgs/msg/ApiRequest`

Purpose: sends RMF task API requests. The mission node uses this to turn mission
move commands into RMF `go_to_place` tasks.

Audience: RMF task API only.

`mission_state`

Type: `std_msgs/msg/String` containing JSON

Purpose: publishes the current mission snapshot.

Audience: web UI, API bridge, operator tools, and developer inspection.

Current issue: this topic currently mixes operator state and debug internals.
The JSON can become large, escaped, and difficult to inspect with `ros2 topic
echo`.

`mission_execution_commands`

Type: `std_msgs/msg/String` containing JSON

Purpose: publishes mission command context for execution-side components. For
move commands, this lets the Free Fleet/Nav2 side channel know which mission
command is associated with the robot movement.

Audience: execution bridge only.

## Current Subscribed Topics

`task_api_responses`

Type: `rmf_task_msgs/msg/ApiResponse`

Purpose: tells the mission node whether RMF accepted a task request.

`task_summaries`

Type: `rmf_task_msgs/msg/TaskSummary`

Purpose: reports RMF task completion. This is one mission command completion
source.

`mission_commands`

Type: `std_msgs/msg/String` containing JSON

Purpose: receives operator/API commands such as mission start.

Audience: web UI/API publishes here.

`mission_execution_results`

Type: `std_msgs/msg/String` containing JSON

Purpose: receives direct execution results from the execution bridge, such as
Free Fleet/Nav2 reporting that a mission command succeeded or failed.

Audience: execution bridge publishes here.

## Topic Design Rule

Topics should be split by audience and purpose:

- operator state
- operator commands
- execution bridge
- event timeline
- debug internals
- RMF integration

The web UI should not need to consume RMF task topics or execution bridge topics
directly. It should mainly consume mission-level topics.

## Recommended Topic Shape

Mission-owned topics should eventually use a common namespace so they are easy
to distinguish from RMF, Nav2, and robot topics.

Recommended mission namespace:

```text
/mission/state
/mission/debug_state
/mission/events
/mission/operator_commands
/mission/execution_commands
/mission/execution_results
```

This is clearer than the current flat names:

```text
/mission_state
/mission_commands
/mission_execution_commands
/mission_execution_results
```

There are two ways to do this in ROS 2:

- hardcode absolute topic names such as `/mission/state`
- run the node under namespace `/mission` and use relative topic names such as
  `state`, `operator_commands`, and `execution_commands`

Using a node namespace is more idiomatic ROS, but hardcoded absolute names are
easier to reason about in a small fixed deployment.

Do not move RMF-owned topics under `/mission`. Keep these as RMF integration
topics:

```text
task_api_requests
task_api_responses
task_summaries
```

Renaming mission topics affects every producer and consumer:

- mission manager constants
- Free Fleet/Nav2 execution bridge
- web/API bridge subscriptions and publishers
- README and runbook commands
- rosbag/debug scripts

The best time to migrate is before the web UI depends heavily on the current
flat topic names.

`mission_state`

The compact, stable, web/UI-facing mission snapshot.

Recommended fields:

- `schema_version`
- `mission.id`
- `mission.name`
- `mission.status`
- `mission.phase`
- `mission.current_step`
- `mission.total_steps`
- `mission.active_robot`
- `mission.current_blocker`
- `mission.next_step`
- `mission.last_update`
- `packages`
- `robots`
- `tasks`
- `zones`
- `operator.active_command_count`
- `operator.blocked_task_count`
- `last_event`
- `last_update_time`

Avoid putting full internal state here:

- full `mission_tasks`
- full `resources`
- full `execution_commands`
- RMF adapter request/task maps
- long recent event/action arrays
- timer internals

`mission_debug_state`

Add this as the verbose developer/debug snapshot.

Recommended fields:

- `mission_id`
- raw `status`
- `total_packages`
- `delivered_count`
- `remaining_count`
- compact `packages`
- raw `robots`
- `transfer`
- `mission_tasks`
- `resources`
- `execution_commands`
- `operator.active_command_count`
- `operator.blocked_task_count`
- `active_task_ids`
- `node_online`
- `last_update_time`
- `debug.last_event`
- `debug.last_action`
- `debug.recent_events`
- `debug.recent_actions`
- `debug.active_handling_commands`
- `debug.pending_request_ids`
- `debug.active_rmf_task_ids`
- `debug.completed_task_ids`

This topic can stay large because it is not the primary UI state path.

`mission_events`

Add this as a small append-style event stream.

Example events:

```json
{"type":"MissionStarted","mission_id":"m1"}
{"type":"TaskBlocked","task_id":"P1:transfer_to_destination","reason":"PACKAGE_NOT_AVAILABLE"}
{"type":"ExecutionCommandCompleted","command_id":"cmd_3","source":"task_summary"}
{"type":"MissionCompleted","mission_id":"m1"}
```

Use this for:

- web UI timeline
- audit trail
- rosbag replay
- understanding why mission state changed

`mission_commands`

Keep this as the mission command input topic.

When namespaced, prefer `/mission/operator_commands`. This makes it clear that
the topic carries operator/UI/API intent, not execution bridge work.

Example commands:

```json
{"command":"start","mission_id":"m1"}
{"command":"pause","mission_id":"m1"}
{"command":"resume","mission_id":"m1"}
{"command":"abort","mission_id":"m1"}
```

`mission_execution_commands`

Keep this as an execution bridge topic. The web UI should not depend on it.

`mission_execution_results`

Keep this as an execution bridge result topic. The web UI should not depend on
it directly.

`task_api_requests`, `task_api_responses`, `task_summaries`

Keep these as RMF integration topics. The web UI should not consume them
directly.

## Recommended Data Flow

Web UI and API:

```text
consume:
  mission_state
  mission_events

publish:
  mission_commands
```

Debug tools:

```text
consume:
  mission_debug_state
  mission_events
  mission_execution_commands
  mission_execution_results
  task_summaries
```

Execution bridge:

```text
consume:
  mission_execution_commands

publish:
  mission_execution_results
```

RMF integration:

```text
consume:
  task_api_requests

publish:
  task_api_responses
  task_summaries
```

## Implemented First Split

The first split keeps JSON and separates the serializers:

- `mission_state`: compact operator-facing state
- `mission_debug_state`: current full verbose state
- `mission_events`: timeline-style event stream

The compact state only receives `last_event` from the mission node. The full
node-local debug context stays in `mission_debug_state.debug`, where it can
include recent event/action arrays, active handling commands, and RMF adapter
request/task maps.

This makes the web UI cleaner and makes terminal debugging easier without losing
internal visibility.
