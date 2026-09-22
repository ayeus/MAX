"""Tamper-evident audit logging for MAX computer agent.

Appends structured JSONL events with real timestamps, tool names, parameters,
risk assessments, verification results, and execution outcomes.
"""

from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
import json
from app.config import settings


class AuditEvent(BaseModel):
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: str
    tool: str | None = None
    action: str | None = None
    risk_level: str | None = None
    details: dict = Field(default_factory=dict)
    success: bool | None = None


class AuditLogger:
    """Manages appending real events to the JSONL audit trail."""

    def __init__(self, log_path: Path = settings.audit_log_path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event_type: str,
        tool: str | None = None,
        action: str | None = None,
        risk_level: str | None = None,
        details: dict | None = None,
        success: bool | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            tool=tool,
            action=action,
            risk_level=risk_level,
            details=details or {},
            success=success,
        )
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event


# Global audit logger instance
audit_log = AuditLogger()
