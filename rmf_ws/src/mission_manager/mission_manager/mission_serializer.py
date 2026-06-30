from dataclasses import asdict, is_dataclass
from enum import Enum
from time import time

from .execution import ExecutionCommandStatus, ExecutionCommandType
from .mission_definition import (
    DESTINATION_WAYPOINT,
    DOWNSTREAM_HOME_WAYPOINT,
    DOWNSTREAM_WAIT_WAYPOINT,
    SOURCE_WAYPOINT,
    TRANSFER_WAYPOINT,
    UPSTREAM_HOME_WAYPOINT,
    UPSTREAM_WAIT_WAYPOINT,
)
from .mission_tasks import MissionTaskStatus, TransportTaskPhase


MISSION_NAME = "Two-robot package handoff"

MISSION_STATUS_TO_UI = {
    "CREATED": "idle",
    "READY": "idle",
    "RUNNING": "active",
    "PAUSED": "paused",
    "COMPLETED": "completed",
    "ABORTED": "cancelled",
    "FAILED": "failed",
}

TASK_STATUS_TO_UI = {
    MissionTaskStatus.PENDING: "pending",
    MissionTaskStatus.RUNNING: "active",
    MissionTaskStatus.BLOCKED: "waiting",
    MissionTaskStatus.SUCCEEDED: "completed",
    MissionTaskStatus.FAILED: "failed",
    MissionTaskStatus.CANCELLED: "cancelled",
}


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _json_value(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _json_value(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def action_to_dict(action):
    if action is None:
        return None
    data = _json_value(action)
    data["type"] = type(action).__name__
    return data


def event_to_dict(event):
    if event is None:
        return None
    data = _json_value(event)
    if not isinstance(data, dict):
        data = {"value": data}
    if "type" not in data:
        data["type"] = "OperatorCommand" if "command" in data else type(event).__name__
    if "message" not in data:
        data["message"] = _event_message(data)
    return data


def serialize_mission_event(event, mission_id: str, timestamp: float | None = None):
    """Serialize one mission event for the append-style mission_events topic."""

    data = event_to_dict(event)
    if data is None:
        return None
    data.setdefault("mission_id", mission_id)
    data.setdefault("timestamp", timestamp if timestamp is not None else time())
    data.setdefault("event_id", f"{mission_id}:{data['timestamp']}")
    return data


def serialize_mission_state(mission_manager, adapter=None, last_event=None):
    """Serialize the compact dashboard/operator mission snapshot."""

    runtime = mission_manager.runtime
    world = runtime.world
    
    active_command_ids = _active_command_ids(mission_manager)
    active_task = _active_task(runtime.tasks)
    last_update_time = time()

    return {
        "schema_version": 1,
        "mission": {
            "id": runtime.mission_id,
            "name": MISSION_NAME,
            "status": MISSION_STATUS_TO_UI.get(runtime.status.value, runtime.status.value.lower()),
            "phase": _mission_phase(runtime.tasks),
            "current_step": _current_step(runtime.tasks),
            "total_steps": len(runtime.tasks),
            "active_robot": active_task.robot_id if active_task is not None else None,
            "current_blocker": _current_blocker(runtime.tasks),
            "next_step": _next_step(runtime.tasks),
            "last_update": last_update_time,
        },
        "packages": _package_summaries(world),
        "robots": _robot_summaries(world, runtime.tasks, mission_manager, adapter, last_update_time),
        "tasks": _task_summaries(runtime.tasks),
        "zones": _zone_summaries(world),
        "operator": {
            "active_command_count": len(active_command_ids),
            "blocked_task_count": sum(
                1 for task in runtime.tasks.values() if task.waiting_resource_id is not None
            ),
        },
        "last_event": last_event,
        "last_update_time": last_update_time,
    }


def serialize_mission_debug_state(mission_manager, adapter=None, node_debug=None):
    """Serialize the verbose developer/debug mission snapshot."""

    runtime = mission_manager.runtime
    world = runtime.world
    debug = node_debug or {}
    total_packages = len(world.items)
    delivered_count = _delivered_count(world)
    active_command_ids = _active_command_ids(mission_manager)

    adapter_debug = {}
    if adapter is not None:
        adapter_debug = {
            "pending_request_ids": list(adapter.command_id_by_request_id.keys()),
            "active_rmf_task_ids": list(adapter.command_id_by_rmf_task_id.keys()),
            "completed_task_ids": list(adapter.completed_rmf_task_ids),
        }

    return {
        "mission_id": runtime.mission_id,
        "status": runtime.status.value,
        "total_packages": total_packages,
        "delivered_count": delivered_count,
        "remaining_count": total_packages - delivered_count,
        "packages": _json_value(_package_summaries(world)),
        "robots": _json_value(world.robots),
        "transfer": _json_value(_transfer_summary(world)),
        "mission_tasks": _json_value(runtime.tasks),
        "resources": _json_value(world.resources),
        "execution_commands": _json_value(mission_manager.execution_manager.commands),
        "operator": {
            "active_command_count": len(active_command_ids),
            "blocked_task_count": sum(
                1 for task in runtime.tasks.values() if task.waiting_resource_id is not None
            ),
        },
        "active_task_ids": active_command_ids,
        "node_online": True,
        "last_update_time": time(),
        "debug": {
            "last_event": debug.get("last_event"),
            "last_action": debug.get("last_action"),
            "recent_events": debug.get("recent_events", []),
            "recent_actions": debug.get("recent_actions", []),
            "active_handling_commands": debug.get("active_handling_commands", []),
            **adapter_debug,
        },
    }


def _event_message(event: dict) -> str:
    event_type = event.get("type")
    if event_type == "MissionStartRequested":
        return f"Mission start requested from {event.get('source')}"
    if event_type == "OperatorPauseRequested":
        return f"Mission pause requested from {event.get('source')}"
    if event_type == "OperatorResumeRequested":
        return f"Mission resume requested from {event.get('source')}"
    if event_type == "OperatorRobotPauseRequested":
        return f"Robot pause requested: {event.get('robot_id')}"
    if event_type == "OperatorRobotResumeRequested":
        return f"Robot resume requested: {event.get('robot_id')}"
    if event_type == "OperatorAbortRequested":
        return f"Mission abort requested from {event.get('source')}"
    if event_type == "ExecutionCommandCompleted":
        return f"Execution command completed from {event.get('source')}: {event.get('command_id')}"
    if event_type == "ExecutionCommandFailed":
        return (
            f"Execution command failed from {event.get('source')}: "
            f"{event.get('command_id')} ({event.get('error')})"
        )
    if event_type == "ExecutionCommandCancelRequested":
        return (
            f"Execution command cancel requested from {event.get('source')}: "
            f"{event.get('command_id')} ({event.get('reason')})"
        )
    if event_type == "ExecutionCommandCancelled":
        return (
            f"Execution command cancelled from {event.get('source')}: "
            f"{event.get('command_id')} ({event.get('reason')})"
        )
    if event_type == "ExecutionCommandRetry":
        return (
            f"Execution command retry after {event.get('failed_command_id')}: "
            f"{event.get('retry_command_ids')}"
        )
    if event_type == "RmfTaskSummaryCompleted":
        return (
            "RMF task summary completed; waiting for Nav2 arrival result: "
            f"{event.get('command_id')}"
        )
    if event_type == "OperatorCommand":
        return f"Operator command requested: {event.get('command')}"
    if "status" in event and "command_id" in event:
        return f"Execution result {event.get('status')}: {event.get('command_id')}"
    return str(event_type or "Mission event")


def _active_command_ids(mission_manager) -> list[str]:
    return [
        command.command_id
        for command in mission_manager.execution_manager.commands.values()
        if command.status
        not in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        )
    ]


def _delivered_count(world) -> int:
    return sum(
        1
        for item in world.items.values()
        if item.location == DESTINATION_WAYPOINT and item.carried_by is None
    )


def _package_summaries(world) -> dict:
    packages = {}
    for item_id, item in world.items.items():
        status = "in_transit"
        if item.carried_by is not None:
            status = "carried"
        elif item.location == DESTINATION_WAYPOINT:
            status = "delivered"
        elif item.location == TRANSFER_WAYPOINT:
            status = "at_transfer"
        elif item.location == SOURCE_WAYPOINT:
            status = "at_source"
        packages[item_id] = {
            "package_id": item_id,
            "status": status,
            "location": item.location,
            "carried_by": item.carried_by,
        }
    return packages


def _robot_summaries(world, tasks, mission_manager, adapter, last_update_time: float) -> list[dict]:
    return [
        {
            "id": robot_id,
            "label": _robot_label(robot_id),
            "mission_state": _robot_mission_state(robot, tasks, mission_manager),
            "paused": robot.paused,
            "speed_scale": robot.speed_scale,
            "active_task_id": robot.active_task_id,
            "location": robot.location,
            "issue": _robot_issue(robot, tasks),
            "rmf_task_id": _rmf_task_id(robot.active_task_id, mission_manager, adapter),
            "last_update": last_update_time,
        }
        for robot_id, robot in sorted(world.robots.items())
    ]


def _robot_label(robot_id: str) -> str:
    if robot_id.startswith("tb3_"):
        return f"Robot {robot_id.removeprefix('tb3_')}"
    return robot_id


def _robot_mission_state(robot, tasks, mission_manager) -> str:
    if robot.paused:
        return "paused"
    if robot.active_task_id is None:
        return "idle"
    task = tasks.get(robot.active_task_id)
    if task is not None and task.status == MissionTaskStatus.BLOCKED:
        return "waiting"
    active_command = _active_command_for_task(robot.active_task_id, mission_manager)
    if active_command is not None and active_command.command_type == ExecutionCommandType.MOVE_ROBOT:
        return "moving"
    return "assigned"


def _robot_issue(robot, tasks) -> str | None:
    if robot.active_task_id is None:
        return None
    task = tasks.get(robot.active_task_id)
    if task is None:
        return None
    return task.blocked_reason or task.next_expected_event


def _rmf_task_id(task_id: str | None, mission_manager, adapter) -> str | None:
    if task_id is None or adapter is None:
        return None
    active_command = _active_command_for_task(task_id, mission_manager)
    if active_command is None:
        return None
    for rmf_task_id, command_id in adapter.command_id_by_rmf_task_id.items():
        if command_id == active_command.command_id:
            return rmf_task_id
    return None


def _task_summaries(tasks) -> list[dict]:
    return [
        {
            "id": task.task_id,
            "label": _task_label(task),
            "status": TASK_STATUS_TO_UI.get(task.status, task.status.value.lower()),
            "phase": task.phase.value,
            "assigned_robot": task.robot_id,
            "start": task.pickup,
            "goal": task.dropoff,
            "dependencies": _task_dependencies(task, tasks),
            "blocked_reason": task.blocked_reason,
            "blocked_by": task.blocked_by,
            "waiting_at": task.waiting_at,
            "unblock_condition": task.unblock_condition,
            "next_expected_event": task.next_expected_event,
            "notes": task.blocked_reason or task.next_expected_event or "",
        }
        for task_id, task in sorted(tasks.items())
    ]


def _task_label(task) -> str:
    return f"Move {task.item_id} from {task.pickup} to {task.dropoff}"


def _task_dependencies(task, tasks) -> list[str]:
    if task.pickup != TRANSFER_WAYPOINT:
        return []
    upstream_task_id = f"{task.item_id}:source_to_transfer"
    return [upstream_task_id] if upstream_task_id in tasks else []


def _zone_summaries(world) -> list[dict]:
    zones = [
        {
            "id": SOURCE_WAYPOINT,
            "label": "Source",
            "type": "pickup",
            "status": "available",
        },
        {
            "id": TRANSFER_WAYPOINT,
            "label": "Transfer Zone",
            "type": "transfer",
            **_transfer_zone_status(world),
        },
        {
            "id": DESTINATION_WAYPOINT,
            "label": "Destination",
            "type": "dropoff",
            "status": "available",
        },
        {
            "id": UPSTREAM_WAIT_WAYPOINT,
            "label": "Upstream Exit",
            "type": "staging",
            "status": "available",
        },
        {
            "id": DOWNSTREAM_WAIT_WAYPOINT,
            "label": "Downstream Exit",
            "type": "staging",
            "status": "available",
        },
        {
            "id": UPSTREAM_HOME_WAYPOINT,
            "label": "Robot 1 Home",
            "type": "base",
            "status": "available",
        },
        {
            "id": DOWNSTREAM_HOME_WAYPOINT,
            "label": "Robot 2 Home",
            "type": "base",
            "status": "available",
        },
    ]
    return zones


def _transfer_zone_status(world) -> dict:
    resource = world.resources.get(TRANSFER_WAYPOINT)
    if resource is None:
        return {"status": "available"}
    occupied_by = resource.robot_occupancy[0] if resource.robot_occupancy else None
    package_buffer = resource.package_occupancy[0] if resource.package_occupancy else None
    return {
        "status": "occupied" if occupied_by or package_buffer else "available",
        "occupied_by": occupied_by,
        "package_buffer": package_buffer,
        "active_lease_owner": resource.active_lease.actor_id if resource.active_lease else None,
    }


def _transfer_summary(world) -> dict:
    resource = world.resources.get(TRANSFER_WAYPOINT)
    return {
        "active_lease": _json_value(resource.active_lease) if resource is not None else None,
        "robot_occupancy": (
            resource.robot_occupancy[0] if resource is not None and resource.robot_occupancy else None
        ),
        "package_buffer": (
            resource.package_occupancy[0]
            if resource is not None and resource.package_occupancy
            else None
        ),
        "waiting_robot": None,
        "waiting_package": None,
    }


def _active_task(tasks):
    for task in tasks.values():
        if task.status in (MissionTaskStatus.RUNNING, MissionTaskStatus.BLOCKED):
            return task
    return None


def _current_step(tasks) -> int:
    if not tasks:
        return 0
    completed = sum(1 for task in tasks.values() if task.status == MissionTaskStatus.SUCCEEDED)
    return min(completed + 1, len(tasks))


def _mission_phase(tasks) -> str:
    task = _active_task(tasks)
    if task is None:
        if all(task.status == MissionTaskStatus.SUCCEEDED for task in tasks.values()):
            return "mission_complete"
        return "idle"
    if task.status == MissionTaskStatus.BLOCKED:
        return "waiting_at_transfer_zone"
    return _phase_for_task(task)


def _phase_for_task(task) -> str:
    if task.phase == TransportTaskPhase.MOVE_TO_PICKUP:
        return "moving_to_pickup"
    if task.phase == TransportTaskPhase.LOAD_ITEM:
        return "loading"
    if task.phase in (TransportTaskPhase.MOVE_TO_WAIT_POINT, TransportTaskPhase.WAIT_FOR_RESOURCE):
        return "waiting_at_transfer_zone"
    if task.phase == TransportTaskPhase.MOVE_TO_DROPOFF:
        return "moving_to_transfer_zone" if task.dropoff == TRANSFER_WAYPOINT else "moving_to_dropoff"
    if task.phase == TransportTaskPhase.UNLOAD_ITEM:
        return "transfer_complete" if task.dropoff == TRANSFER_WAYPOINT else "dropoff_reached"
    if task.phase == TransportTaskPhase.MOVE_TO_TRANSFER_EXIT:
        return "transfer_complete"
    if task.phase == TransportTaskPhase.DONE:
        return "mission_complete"
    return task.phase.value.lower()


def _current_blocker(tasks) -> str | None:
    for task in tasks.values():
        if task.status == MissionTaskStatus.BLOCKED:
            return task.blocked_reason or task.next_expected_event
    return None


def _next_step(tasks) -> str | None:
    active = _active_task(tasks)
    if active is not None:
        return active.next_expected_event or active.phase.value.lower()
    for task_id, task in sorted(tasks.items()):
        if task.status == MissionTaskStatus.PENDING:
            return task_id
    return None


def _active_command_for_task(task_id: str | None, mission_manager):
    if task_id is None:
        return None
    for command in mission_manager.execution_manager.commands.values():
        if command.task_id != task_id:
            continue
        if command.status in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        ):
            continue
        return command
    return None
