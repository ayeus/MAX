"""Structured speech interpretation representation for MAX."""

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


class SpeechInterpretation(BaseModel):
    """Structured representation of interpreted user speech."""

    raw_text: str
    normalized_text: str
    confidence: float = 1.0
    corrections: list[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    clarification_prompt: Optional[str] = None
    alternatives: list[str] = Field(default_factory=list)
    intent: Optional[str] = None
    target: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
