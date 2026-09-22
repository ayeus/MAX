"""Base definitions and data structures for MAX verification architecture."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class GoalStatus(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


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
