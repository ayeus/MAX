"""Structured Goal and Subgoal models for MAX 2.0 closed-loop execution engine."""

from __future__ import annotations
from enum import Enum
import time
from typing import Any, Optional, TYPE_CHECKING
import uuid
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from capabilities.accessibility.models import ComputerState, UIElement


class SubgoalStatus(str, Enum):
    """Execution status of a goal or subgoal."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"
    CANCELLED = "CANCELLED"


from verification.base import PostconditionType, ExpectedPostcondition
from capabilities.accessibility.models import TargetReference


class ActionType(str, Enum):
    """Supported semantic action intent types."""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    FOCUS = "focus"
    TYPE_TEXT = "type_text"
    REPLACE_TEXT = "replace_text"
    PRESS_KEY = "press_key"
    KEY_CHORD = "key_chord"
    SCROLL = "scroll"
    SELECT = "select"
    NAVIGATE = "navigate"
    WAIT_FOR_STATE = "wait_for_state"
    SEND = "send"
    SUBMIT = "submit"


class ActionIntent(BaseModel):
    """High-level semantic action intent decoupled from hardcoded screen coordinates."""

    action_type: str | ActionType
    target_ref: Optional[TargetReference] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_postcondition: Optional[ExpectedPostcondition] = None
    grounding_evidence: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        """Enforce structural invariants."""
        act = self.action_type.value if isinstance(self.action_type, ActionType) else str(self.action_type).lower()
        if act == "type_text" and self.parameters.get("press_return"):
            raise ValueError(
                "Structural safety violation: TYPE_TEXT cannot have press_return=True (Rule 12: Type != Send). "
                "Sending or submitting requires an explicit ActionType.SEND or ActionType.SUBMIT action."
            )



class Subgoal(BaseModel):
    """A concrete, verifiable milestone in achieving a user goal."""

    id: str = Field(default_factory=lambda: f"subgoal_{uuid.uuid4().hex[:8]}")
    description: str
    target_description: Optional[str] = None
    target_constraints: Optional[dict[str, Any]] = None
    action_intent: Optional[ActionIntent] = None
    expected_postcondition: Optional[ExpectedPostcondition] = None
    status: SubgoalStatus = SubgoalStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    evidence: dict[str, Any] = Field(default_factory=dict)


class Goal(BaseModel):
    """Structured representation of the overall task objective and remaining subgoals."""

    objective: str
    subgoals: list[Subgoal] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    status: SubgoalStatus = SubgoalStatus.PENDING
    current_subgoal_index: int = 0

    def get_current_subgoal(self) -> Optional[Subgoal]:
        """Retrieve the currently active subgoal."""
        if 0 <= self.current_subgoal_index < len(self.subgoals):
            return self.subgoals[self.current_subgoal_index]
        return None

    def advance_subgoal(self) -> Optional[Subgoal]:
        """Mark active subgoal satisfied and advance to next."""
        current = self.get_current_subgoal()
        if current:
            current.status = SubgoalStatus.SATISFIED
        self.current_subgoal_index += 1
        next_subgoal = self.get_current_subgoal()
        if not next_subgoal:
            self.status = SubgoalStatus.SATISFIED
        else:
            next_subgoal.status = SubgoalStatus.IN_PROGRESS
        return next_subgoal

    def fail_current_subgoal(self, reason: str):
        """Mark active subgoal as unsatisfied and record failure reason."""
        current = self.get_current_subgoal()
        if current:
            current.status = SubgoalStatus.UNSATISFIED
            current.evidence["failure_reason"] = reason
        self.status = SubgoalStatus.UNSATISFIED

    def is_complete(self) -> bool:
        """Check if goal is in a terminal state."""
        return self.status in (SubgoalStatus.SATISFIED, SubgoalStatus.CANCELLED, SubgoalStatus.UNSATISFIED)

    def all_satisfied(self) -> bool:
        """Check if all subgoals are satisfied."""
        return len(self.subgoals) > 0 and all(sg.status == SubgoalStatus.SATISFIED for sg in self.subgoals)
