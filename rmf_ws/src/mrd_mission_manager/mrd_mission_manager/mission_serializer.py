from dataclasses import asdict, is_dataclass
from enum import Enum
from time import time

from .execution import ExecutionCommandStatus
from .mission_definition import DESTINATION_WAYPOINT, TRANSFER_WAYPOINT


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
    data["type"] = type(event).__name__
    return data


def serialize_runtime_mission_state(orchestrator, adapter=None, node_debug=None):
    runtime = orchestrator.runtime
    world = runtime.world
    debug = node_debug or {}
    total_packages = len(world.items)
    delivered_count = sum(
        1
        for item in world.items.values()
        if item.location == DESTINATION_WAYPOINT and item.carried_by is None
    )
    active_command_ids = [
        command.command_id
        for command in orchestrator.execution.commands.values()
        if command.status
        not in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        )
    ]

    packages = {}
    for item_id, item in world.items.items():
        status = "IN_TRANSIT"
        if item.carried_by is not None:
            status = "CARRIED"
        elif item.location == DESTINATION_WAYPOINT:
            status = "DELIVERED"
        elif item.location == TRANSFER_WAYPOINT:
            status = "AT_TRANSFER"
        packages[item_id] = {
            "package_id": item_id,
            "status": status,
            "location": item.location,
            "carried_by": item.carried_by,
        }

    transfer_resource = world.resources.get(TRANSFER_WAYPOINT)
    transfer = {
        "robot_occupancy": (
            transfer_resource.robot_occupancy[0]
            if transfer_resource is not None and transfer_resource.robot_occupancy
            else None
        ),
        "package_buffer": (
            transfer_resource.package_occupancy[0]
            if transfer_resource is not None and transfer_resource.package_occupancy
            else None
        ),
        "waiting_robot": None,
        "waiting_package": None,
    }

    adapter_debug = {}
    if adapter is not None:
        adapter_debug = {
            "pending_request_ids": list(adapter.pending_commands.keys()),
            "active_rmf_task_ids": list(adapter.command_context_by_rmf_task_id.keys()),
            "completed_task_ids": list(adapter.completed_rmf_task_ids),
        }

    return {
        "mission_id": runtime.mission_id,
        "status": runtime.status.value,
        "total_packages": total_packages,
        "delivered_count": delivered_count,
        "remaining_count": total_packages - delivered_count,
        "packages": _json_value(packages),
        "robots": _json_value(world.robots),
        "transfer": _json_value(transfer),
        "mission_tasks": _json_value(runtime.tasks),
        "resources": _json_value(world.resources),
        "execution_commands": _json_value(orchestrator.execution.commands),
        "active_task_ids": active_command_ids,
        "node_online": True,
        "last_update_time": time(),
        "debug": {
            "last_event": debug.get("last_event"),
            "last_action": debug.get("last_action"),
            "recent_events": debug.get("recent_events", []),
            "recent_actions": debug.get("recent_actions", []),
            "active_handling_timers": debug.get("active_handling_timers", []),
            **adapter_debug,
        },
    }
