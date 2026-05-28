import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .execution import ExecutionCommand, ExecutionCommandType
from .mission_definition import FLEET_NAME, REQUESTER
from .world import RuntimeWorld


@dataclass(frozen=True)
class RmfExecutionAdapterConfig:
    fleet_name: str = FLEET_NAME
    requester: str = REQUESTER


class RmfExecutionAdapter:
    def __init__(
        self,
        config: RmfExecutionAdapterConfig | None = None,
        publish_request=None,
        logger=None,
    ):
        self.config = config or RmfExecutionAdapterConfig()
        self.publish_request = publish_request
        self.logger = logger
        self.pending_commands: dict[str, str] = {}
        self.command_context_by_rmf_task_id: dict[str, str] = {}
        self.completed_rmf_task_ids: set[str] = set()

    def build_payload(self, command: ExecutionCommand, world: RuntimeWorld) -> dict[str, Any]:
        if command.command_type != ExecutionCommandType.MOVE_ROBOT or command.target is None:
            raise ValueError(f"Unsupported RMF execution command: {command}")

        robot = world.robots[command.robot_id]
        places = [command.target]
        if robot.location != command.target:
            places = [robot.location, command.target]

        return {
            "type": "robot_task_request",
            "robot": command.robot_id,
            "fleet": self.config.fleet_name,
            "request": {
                "category": "patrol",
                "fleet_name": self.config.fleet_name,
                "description": {
                    "places": places,
                    "rounds": 1,
                },
                "labels": [
                    "app=mrd_mission_manager",
                    f"command_id={command.command_id}",
                    f"task_id={command.task_id}",
                ],
                "requester": self.config.requester,
            },
        }

    def submit_command(self, command: ExecutionCommand, world: RuntimeWorld) -> str:
        request_id = f"mission_{uuid4()}"
        payload = self.build_payload(command, world)
        self.pending_commands[request_id] = command.command_id

        if self.publish_request is not None:
            self.publish_request(request_id, json.dumps(payload))

        return request_id

    def handle_api_response(self, msg) -> str | None:
        responding_type = getattr(msg, "TYPE_RESPONDING", 2)
        if hasattr(msg, "type") and msg.type != responding_type:
            return None

        command_id = self.pending_commands.pop(msg.request_id, None)
        if command_id is None:
            return None

        response = json.loads(msg.json_msg)
        if not response.get("success"):
            self._log_warning(f"RMF rejected execution command: {response}")
            return None

        task_id = self._task_id_from_response(response)
        if task_id is None:
            self._log_warning(f"RMF command response has no task ID: {response}")
            return None

        self.command_context_by_rmf_task_id[task_id] = command_id
        return command_id

    def command_from_completed_task(self, task_id: str) -> str | None:
        if task_id in self.completed_rmf_task_ids:
            return None

        command_id = self.command_context_by_rmf_task_id.get(task_id)
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

    def _log_warning(self, message: str) -> None:
        if self.logger is not None:
            self.logger.warning(message)
