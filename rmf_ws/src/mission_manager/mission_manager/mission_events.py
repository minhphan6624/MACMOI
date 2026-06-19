from dataclasses import dataclass


@dataclass
class MissionStartRequested:
    """Request to start the current mission."""
    source: str = "operator"


@dataclass
class OperatorPauseRequested:
    """Request to pause mission advancement."""

    source: str = "operator"


@dataclass
class OperatorResumeRequested:
    """Request to resume a paused mission."""

    source: str = "operator"


@dataclass
class OperatorAbortRequested:
    """Request to abort the current mission."""

    source: str = "operator"

# ----- Execution command events -----

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


@dataclass
class ExecutionCommandCancelRequested:
    """Cancellation requested for an active execution command."""

    command_id: str
    reason: str
    source: str
    details: dict | None = None


@dataclass
class ExecutionCommandCancelled:
    """External execution command cancellation event."""

    command_id: str
    reason: str
    source: str
    details: dict | None = None


@dataclass
class ExecutionCommandRetry:
    """Retry commands emitted after an execution command failure."""

    failed_command_id: str
    retry_command_ids: list[str]
    reason: str

# ---- Event for When an RMF task is completed -----

@dataclass
class RmfTaskSummaryCompleted:
    """RMF task lifecycle completion observed for an execution command."""

    command_id: str
    rmf_task_id: str
    source: str = "task_summary"
    message: str = (
        "RMF task summary completed; waiting for Nav2 arrival result before "
        "advancing mission"
    )
