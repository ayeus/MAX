"""Structured models and lifecycle states for managed background tasks in MAX."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field
import uuid
from typing import Any, Optional


class TaskState(str, Enum):
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    UNKNOWN = "UNKNOWN"


class TaskType(str, Enum):
    COMMAND = "COMMAND"              # Finite shell command (e.g. build, tests, script)
    DAEMON = "DAEMON"                # Persistent background service (e.g. dev server, backend)
    FS_WATCHER = "FS_WATCHER"        # Filesystem change observer
    PORT_MONITOR = "PORT_MONITOR"    # TCP port/service observer


def generate_task_id() -> str:
    """Generate collision-resistant task identifier."""
    return f"tsk_{uuid.uuid4().hex[:12]}"


class ManagedTask(BaseModel):
    """Represents a long-running, supervised background task managed by MAX."""

    task_id: str = Field(default_factory=generate_task_id)
    command: str
    task_type: TaskType = TaskType.COMMAND
    status: TaskState = TaskState.CREATED
    pid: Optional[int] = None
    pgid: Optional[int] = None
    working_dir: str = Field(default_factory=lambda: str(Path.cwd()))
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None
    log_file: str = ""
    original_request: Optional[str] = None
    max_runtime_seconds: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        """Return True if task is currently executing or waiting."""
        return self.status in (TaskState.STARTING, TaskState.RUNNING, TaskState.WAITING)

    @property
    def is_terminal(self) -> bool:
        """Return True if task has reached a final execution state."""
        return self.status in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.TIMED_OUT)
