from dataclasses import asdict, is_dataclass
from enum import Enum
from time import time


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


def serialize_mission_state(manager, bridge=None, node_debug=None):
    state = manager.state
    debug = node_debug or {}
    active_task_ids = [
        robot.active_task_id
        for robot in state.robots.values()
        if robot.active_task_id is not None
    ]

    bridge_debug = {}
    if bridge is not None:
        bridge_debug = {
            "pending_request_ids": list(bridge.pending_actions.keys()),
            "active_rmf_task_ids": list(bridge.task_context_by_id.keys()),
            "completed_task_ids": list(bridge.completed_task_ids),
        }

    return {
        "mission_id": state.mission_id,
        "status": state.status.value,
        "total_packages": state.total_packages,
        "delivered_count": state.delivered_count,
        "remaining_count": state.total_packages - state.delivered_count,
        "packages": _json_value(state.packages),
        "robots": _json_value(state.robots),
        "transfer": _json_value(state.transfer),
        "active_task_ids": active_task_ids,
        "node_online": True,
        "last_update_time": time(),
        "debug": {
            "last_event": debug.get("last_event"),
            "last_action": debug.get("last_action"),
            "recent_events": debug.get("recent_events", []),
            "recent_actions": debug.get("recent_actions", []),
            "active_handling_timers": debug.get("active_handling_timers", []),
            **bridge_debug,
        },
    }
