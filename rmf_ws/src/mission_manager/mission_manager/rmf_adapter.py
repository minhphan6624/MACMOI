import json
from typing import Any

from .execution import ExecutionCommand, ExecutionCommandType
from .mission_definition import FLEET_NAME
from .world import MissionWorld


class RmfAdapter:
    """Converts mission execution commands to RMF task API requests."""

    def __init__(
        self,
        mission_id: str = "mission",
        publish_request=None,
        logger=None,
    ):
        """Initialize RMF request tracking and optional publish/log hooks."""

        self.mission_id = mission_id
        self.publish_request = publish_request
        self.logger = logger
        self.command_id_by_request_id: dict[str, str] = {}
        self.command_id_by_rmf_task_id: dict[str, str] = {}
        self.completed_rmf_task_ids: set[str] = set()

    def build_payload(self, command: ExecutionCommand, world: MissionWorld) -> dict[str, Any]:
        """Build an RMF compose task payload for a move command."""

        if command.command_type != ExecutionCommandType.MOVE_ROBOT or command.target is None:
            raise ValueError(f"Unsupported RMF execution command: {command}")

        return {
            "type": "robot_task_request",
            "robot": command.robot_id,
            "fleet": FLEET_NAME,
            "request": {
                "category": "compose",
                "fleet_name": FLEET_NAME,
                "description": {
                    "category": "go_to_place",
                    "phases": [
                        {
                            "activity": {
                                "category": "go_to_place",
                                "description": {
                                    "one_of": [{"waypoint": command.target}],
                                },
                            },
                        }
                    ],
                },
                "labels": [
                    "app=mission_manager",
                    f"command_id={command.command_id}",
                    f"task_id={command.task_id}",
                ],
                "requester": "mission_manager",
            },
        }

    def submit_command(self, command: ExecutionCommand, world: MissionWorld) -> str:
        """Publish a mission execution command as an RMF task request."""

        request_id = f"{self.mission_id}_{command.command_id}"

        payload = self.build_payload(command, world)
        self.command_id_by_request_id[request_id] = command.command_id

        if self.publish_request is not None:
            self.publish_request(request_id, json.dumps(payload))

        return request_id

    def handle_api_response(self, msg) -> str | None:
        """Map a successful RMF API response back to a mission command ID."""

        responding_type = getattr(msg, "TYPE_RESPONDING", 2)
        if hasattr(msg, "type") and msg.type != responding_type:
            return None

        command_id = self.command_id_by_request_id.pop(msg.request_id, None)
        if command_id is None:
            return None

        response = json.loads(msg.json_msg)
        if not response.get("success"):

            if self.logger is not None:
                self.logger.warning(f"RMF rejected execution command: {response}")

            return None

        task_id = self._task_id_from_response(response)
        if task_id is None:

            if self.logger is not None:
                self.logger.warning(f"RMF command response has no task ID: {response}")

            return None

        self.command_id_by_rmf_task_id[task_id] = command_id
        return command_id

    def command_from_completed_task(self, task_id: str) -> str | None:
        """Return the mission command for a newly completed RMF task."""

        if task_id in self.completed_rmf_task_ids:
            return None

        command_id = self.command_id_by_rmf_task_id.get(task_id)
        if command_id is None:
            return None

        self.completed_rmf_task_ids.add(task_id)
        return command_id

    def _task_id_from_response(self, response: dict[str, Any]) -> str | None:

        state = response.get("state")
        if not isinstance(state, dict):
            return None

        booking = state.get("booking")
        if not isinstance(booking, dict):
            return None

        task_id = booking.get("id")
        return task_id if isinstance(task_id, str) else None
