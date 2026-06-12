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

`mission_state`

Keep this as the compact, stable, web/UI-facing mission snapshot.

Recommended fields:

- `mission_id`
- `status`
- `total_packages`
- `delivered_count`
- `remaining_count`
- `packages`
- `robots`
- `transfer`
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

- `mission_tasks`
- `resources`
- `execution_commands`
- `recent_events`
- `recent_actions`
- `active_handling_commands`
- pending RMF request IDs
- active RMF task IDs
- completed RMF task IDs

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

## Practical Next Step

Keep JSON for now, but split the serializers:

- `mission_state`: compact operator-facing state
- `mission_debug_state`: current full verbose state

After that, add `mission_events` for timeline-style inspection. This will make
the web UI cleaner and make terminal debugging easier without losing internal
visibility.
