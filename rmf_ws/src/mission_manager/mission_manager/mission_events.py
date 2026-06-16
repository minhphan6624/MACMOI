from dataclasses import dataclass


@dataclass
class MissionStartRequested:
    """Request to start the current mission."""

    source: str = "operator"


@dataclass
class ExecutionCommandCompleted:
    """External execution command completion event."""

    command_id: str
    source: str
    rmf_task_id: str | None = None


@dataclass
class ExecutionCommandFailed:
    """External execution command failure event."""

    command_id: str
    error: str
    source: str
    details: dict | None = None
