from dataclasses import dataclass
from enum import Enum
from itertools import count


class ExecutionCommandType(Enum):
    """Kinds of external work the mission layer can request."""

    MOVE_ROBOT = "move_robot"
    HANDLE_ITEM = "handle_item"


class ExecutionCommandStatus(Enum):
    """Lifecycle state for a mission execution command."""

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class ExecutionCommand:
    """Command emitted by mission logic for ROS/RMF execution."""

    command_id: str
    command_type: ExecutionCommandType
    task_id: str
    robot_id: str
    target: str | None = None
    item_id: str | None = None
    handling_type: str | None = None
    status: ExecutionCommandStatus = ExecutionCommandStatus.PENDING
    error: str | None = None


class ExecutionManager:
    """Creates and tracks execution commands for mission tasks."""

    def __init__(self):
        self.commands: dict[str, ExecutionCommand] = {}
        self._counter = count(1)

    def create_move(self, task_id: str, robot_id: str, target: str) -> ExecutionCommand:
        """Create and store a robot movement command."""

        return self._add_command(
            ExecutionCommand(
                command_id=self._next_command_id(),
                command_type=ExecutionCommandType.MOVE_ROBOT,
                task_id=task_id,
                robot_id=robot_id,
                target=target,
            )
        )

    def create_handling(
        self,
        task_id: str,
        robot_id: str,
        item_id: str,
        handling_type: str,
    ) -> ExecutionCommand:
        """Create and store a package handling command."""

        return self._add_command(
            ExecutionCommand(
                command_id=self._next_command_id(),
                command_type=ExecutionCommandType.HANDLE_ITEM,
                task_id=task_id,
                robot_id=robot_id,
                item_id=item_id,
                handling_type=handling_type,
            )
        )

    def mark_submitted(self, command_id: str) -> None:
        self.commands[command_id].status = ExecutionCommandStatus.SUBMITTED

    def mark_running(self, command_id: str) -> None:
        self.commands[command_id].status = ExecutionCommandStatus.RUNNING

    def mark_succeeded(self, command_id: str) -> bool:
        command = self.commands[command_id]
        if command.status in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        ):
            return False
        command.status = ExecutionCommandStatus.SUCCEEDED
        return True

    def mark_failed(self, command_id: str, error: str) -> bool:
        command = self.commands[command_id]
        if command.status in (
            ExecutionCommandStatus.SUCCEEDED,
            ExecutionCommandStatus.FAILED,
            ExecutionCommandStatus.CANCELLED,
        ):
            return False
        command.status = ExecutionCommandStatus.FAILED
        command.error = error
        return True

    def _add_command(self, command: ExecutionCommand) -> ExecutionCommand:
        self.commands[command.command_id] = command
        return command

    def _next_command_id(self) -> str:
        return f"cmd_{next(self._counter)}"
