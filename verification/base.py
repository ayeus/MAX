"""Base definitions and data structures for MAX verification architecture."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class GoalStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"
    UNSUPPORTED = "UNSUPPORTED"


class AgentState(str, Enum):
    IDLE = "IDLE"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    REPLANNING = "REPLANNING"
    SPEAKING = "SPEAKING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    DONE = "DONE"
    UNSUPPORTED = "UNSUPPORTED"



class VerificationResult(BaseModel):
    """Result of verifying a specific action or criteria."""
    status: GoalStatus
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class GoalEvaluation(BaseModel):
    """Overall evaluation of whether the user's high-level goal has been satisfied."""
    status: GoalStatus
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    verified_steps: list[int] = Field(default_factory=list)
    remaining_requirements: list[str] = Field(default_factory=list)


class PostconditionType(str, Enum):
    """Categorization of verifiable postconditions."""

    TEXT_VALUE_EQUALS = "TEXT_VALUE_EQUALS"
    TEXT_VALUE_CONTAINS = "TEXT_VALUE_CONTAINS"
    ELEMENT_FOCUSED = "ELEMENT_FOCUSED"
    WINDOW_ACTIVE = "WINDOW_ACTIVE"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    ELEMENT_DISAPPEARED = "ELEMENT_DISAPPEARED"
    ELEMENT_SELECTED = "ELEMENT_SELECTED"
    STATE_DELTA_MATCH = "STATE_DELTA_MATCH"
    APPLICATION_RUNNING = "APPLICATION_RUNNING"
    APPLICATION_TERMINATED = "APPLICATION_TERMINATED"
    FILE_EXISTS = "FILE_EXISTS"
    CUSTOM = "CUSTOM"


class ExpectedPostcondition(BaseModel):
    """Expected state transition that proves an action succeeded."""

    postcondition_type: PostconditionType
    target_path: Optional[str] = None
    expected_value: Optional[str] = None
    expected_window: Optional[str] = None
    expected_application: Optional[str] = None
    expected_delta_keys: list[str] = Field(default_factory=list)
    custom_verifier_name: Optional[str] = None
    description: Optional[str] = None


