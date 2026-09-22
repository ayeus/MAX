"""Tamper-evident, cryptographically chained audit logging for MAX computer agent.

Implements:
1. Cryptographic SHA-256 hash chaining:
   event_hash = sha256(previous_hash + canonical_event_payload)
2. Sensitive data redaction filter:
   Filters passwords, API tokens, secret keys, private keys before disk persistence.
3. Verification function:
   verify_audit_log(log_path) -> tuple[bool, str]
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from pydantic import BaseModel, Field
import re
from typing import Any, Optional
from app.config import settings

GENESIS_HASH = "0" * 64

REDACT_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{15,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"password['\"]?\s*[:=]\s*['\"]?[^\s'\"]+", re.IGNORECASE), "password=[REDACTED]"),
    (re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC )?PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
]


def redact_sensitive_data(val: Any) -> Any:
    """Recursively scrub known sensitive tokens, passwords, and private keys."""
    if isinstance(val, str):
        res = val
        for pat, replacement in REDACT_PATTERNS:
            res = pat.sub(replacement, res)
        return res
    elif isinstance(val, dict):
        return {k: redact_sensitive_data(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [redact_sensitive_data(x) for x in val]
    return val


class AuditEvent(BaseModel):
    sequence: int = 0
    previous_hash: str = GENESIS_HASH
    event_hash: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: str
    tool: str | None = None
    action: str | None = None
    risk_level: str | None = None
    details: dict = Field(default_factory=dict)
    success: bool | None = None

    def compute_hash(self) -> str:
        """Compute SHA-256 hash from canonical payload and previous_hash."""
        payload = {
            "sequence": self.sequence,
            "previous_hash": self.previous_hash,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "tool": self.tool,
            "action": self.action,
            "risk_level": self.risk_level,
            "details": self.details,
            "success": self.success,
        }
        canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class AuditLogger:
    """Manages appending cryptographically chained events to the audit trail."""

    def __init__(self, log_path: Path = settings.audit_log_path):
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._read_tail_hash()
        self._sequence = self._read_tail_sequence()

    def _read_tail_hash(self) -> str:
        """Read the last recorded event hash or return GENESIS_HASH."""
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return GENESIS_HASH
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                if lines:
                    last_obj = json.loads(lines[-1])
                    return last_obj.get("event_hash", GENESIS_HASH)
        except Exception:
            pass
        return GENESIS_HASH

    def _read_tail_sequence(self) -> int:
        """Read the last sequence number or return 0."""
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return 0
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
                if lines:
                    last_obj = json.loads(lines[-1])
                    return last_obj.get("sequence", 0)
        except Exception:
            pass
        return 0

    def log_event(
        self,
        event_type: str,
        tool: str | None = None,
        action: str | None = None,
        risk_level: str | None = None,
        details: dict | None = None,
        success: bool | None = None,
    ) -> AuditEvent:
        """Log a new audit event with sensitive data redacted and cryptographically chained."""
        clean_details = redact_sensitive_data(details or {})
        self._sequence += 1

        event = AuditEvent(
            sequence=self._sequence,
            previous_hash=self._last_hash,
            event_type=event_type,
            tool=tool,
            action=action,
            risk_level=risk_level,
            details=clean_details,
            success=success,
        )
        event.event_hash = event.compute_hash()
        self._last_hash = event.event_hash

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
        return event


def verify_audit_log(log_path: Path) -> tuple[bool, str]:
    """Verify cryptographic hash chaining across the entire audit log."""
    if not log_path.exists():
        return True, "Log file does not exist (empty valid state)."

    expected_prev = GENESIS_HASH
    expected_seq = 1

    with open(log_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                event = AuditEvent(**data)
            except Exception as e:
                return False, f"Line {line_num}: JSON parsing failure: {e}"

            if event.sequence != expected_seq:
                return False, f"Line {line_num}: Sequence mismatch: expected {expected_seq}, got {event.sequence}"

            if event.previous_hash != expected_prev:
                return False, f"Line {line_num}: Previous hash mismatch: expected {expected_prev}, got {event.previous_hash}"

            computed = event.compute_hash()
            if event.event_hash != computed:
                return False, f"Line {line_num}: Tampered event hash: recorded {event.event_hash}, computed {computed}"

            expected_prev = event.event_hash
            expected_seq += 1

    return True, f"Audit log verified: {expected_seq - 1} cryptographically chained events valid."


# Global audit logger instance
audit_log = AuditLogger()
