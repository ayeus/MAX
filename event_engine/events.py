"""Event definitions for MAX asynchronous event engine."""

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field
import uuid
from typing import Any, Optional


class EventType(str, Enum):
    # Process & Task Lifecycle
    PROCESS_STARTED = "process.started"
    PROCESS_EXITED = "process.exited"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_TIMED_OUT = "task.timed_out"

    # Filesystem Events
    FILE_CREATED = "fs.created"
    FILE_MODIFIED = "fs.modified"
    FILE_DELETED = "fs.deleted"
    FILE_MOVED = "fs.moved"

    # Service / Port Events
    SERVICE_STATUS_CHANGED = "service.status_changed"


def generate_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:12]}"


class Event(BaseModel):
    """Base event model carrying structured telemetry and payload data."""

    event_id: str = Field(default_factory=generate_event_id)
    event_type: EventType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str
    task_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class ProcessStartedEvent(Event):
    event_type: EventType = EventType.PROCESS_STARTED
    pid: int
    pgid: int
    command: str


class ProcessExitedEvent(Event):
    event_type: EventType = EventType.PROCESS_EXITED
    pid: int
    exit_code: int
    duration_ms: float = 0.0


class TaskCompletedEvent(Event):
    event_type: EventType = EventType.TASK_COMPLETED
    exit_code: int = 0
    duration_ms: float = 0.0


class TaskFailedEvent(Event):
    event_type: EventType = EventType.TASK_FAILED
    exit_code: Optional[int] = None
    error: str = ""
    duration_ms: float = 0.0


class TaskCancelledEvent(Event):
    event_type: EventType = EventType.TASK_CANCELLED
    reason: str = "User requested cancellation"


class FileEvent(Event):
    path: str
    is_directory: bool = False


class FileCreatedEvent(FileEvent):
    event_type: EventType = EventType.FILE_CREATED


class FileModifiedEvent(FileEvent):
    event_type: EventType = EventType.FILE_MODIFIED


class FileDeletedEvent(FileEvent):
    event_type: EventType = EventType.FILE_DELETED


class ServiceStatusChangedEvent(Event):
    event_type: EventType = EventType.SERVICE_STATUS_CHANGED
    service_name: str
    port: int
    is_listening: bool
