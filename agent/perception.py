"""Automatic Perception Fallback Pipeline for MAX 2.0.

Priority:
1. Native macOS Accessibility Semantics (authoritative, structured, fast)
2. Keyboard / Navigation Strategy (for focus/tabbing)
3. Dynamic Computer-Vision Fallback (when accessibility tree lacks the element)

Guarantees:
- Zero stored coordinates: visual coordinates are tied strictly to the current snapshot.
- Zero blind actions: if ambiguous in accessibility, perception refuses blind guessing.
- Zero fake success: vision failures or malformed outputs evaluate to UNKNOWN.
"""

from __future__ import annotations
from enum import Enum
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from capabilities.accessibility.models import UIElement, ComputerState
from capabilities.accessibility.grounding import (
    ui_grounder,
    TargetConstraints,
    GroundingMatch,
    GroundingConfidence,
)
from agent.goal import TargetReference

logger = logging.getLogger(__name__)


class PerceptionMethod(str, Enum):
    """The perception channel that resolved the target."""

    ACCESSIBILITY = "ACCESSIBILITY"
    KEYBOARD_NAV = "KEYBOARD_NAV"
    VISION = "VISION"
    NONE = "NONE"


class PerceptionResult(BaseModel):
    """Structured perception output resolving an action target against the current computer state."""

    method: PerceptionMethod = PerceptionMethod.NONE
    element: Optional[UIElement] = None
    target_ref: Optional[TargetReference] = None
    dynamic_coordinates: Optional[tuple[float, float]] = None
    confidence: GroundingConfidence = GroundingConfidence.NONE
    rationale: str = ""
    is_ambiguous: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        """Determines if the perception result is reliable enough for action execution."""
        if self.is_ambiguous:
            return False
        if self.method == PerceptionMethod.ACCESSIBILITY:
            return self.element is not None and self.confidence in (
                GroundingConfidence.EXACT,
                GroundingConfidence.STRONG,
            )
        if self.method == PerceptionMethod.VISION:
            return self.dynamic_coordinates is not None
        return False


class PerceptionPipeline:
    """Orchestrates multi-channel target grounding with strict fallback order."""

    def __init__(self, vision_capability: Optional[Any] = None):
        self._vision_cap = vision_capability

    def set_vision_capability(self, vision_cap: Any):
        self._vision_cap = vision_cap

    def resolve_target(
        self,
        constraints: TargetConstraints,
        current_state: ComputerState,
        allow_vision: bool = True,
    ) -> PerceptionResult:
        """Resolve a target using Accessibility first, falling back to Vision dynamically if needed."""
        # 1. Semantic Accessibility Grounding
        ax_match: GroundingMatch = ui_grounder.ground(constraints, current_state)

        # Ambiguity in accessibility tree must be respected immediately
        if ax_match.is_ambiguous:
            return PerceptionResult(
                method=PerceptionMethod.ACCESSIBILITY,
                element=None,
                target_ref=None,
                confidence=GroundingConfidence.WEAK,
                rationale=ax_match.rationale,
                is_ambiguous=True,
                evidence={
                    "candidates_count": ax_match.candidates_count,
                    "alternatives": ax_match.alternative_labels,
                },
            )

        if ax_match.is_reliable and ax_match.element:
            return PerceptionResult(
                method=PerceptionMethod.ACCESSIBILITY,
                element=ax_match.element,
                target_ref=ax_match.target_ref,
                dynamic_coordinates=None,
                confidence=ax_match.confidence,
                rationale=ax_match.rationale,
                is_ambiguous=False,
                evidence={
                    "path": ax_match.element.path,
                    "role": ax_match.element.role,
                    "bounds": ax_match.element.bounds,
                },
            )

        # 2. Check if accessibility observation is truncated and we should attempt targeted expansion
        if current_state.observation_metadata and current_state.observation_metadata.is_truncated:
            logger.info("Accessibility tree was truncated; target '%s' may exist in unexpanded subtrees", constraints.label)

        # 3. Vision Fallback (when Accessibility is insufficient)
        target_desc = constraints.label or constraints.role or ""
        if allow_vision and self._vision_cap and target_desc:
            logger.info("Accessibility resolution insufficient. Attempting dynamic Vision fallback for '%s'", target_desc)
            try:
                vis_res = self._vision_cap.find_visual_target(target_description=target_desc)
                if vis_res.success and vis_res.data and "coordinates" in vis_res.data:
                    coords = vis_res.data["coordinates"]
                    if isinstance(coords, (list, tuple)) and len(coords) == 2:
                        cx, cy = float(coords[0]), float(coords[1])
                        return PerceptionResult(
                            method=PerceptionMethod.VISION,
                            element=None,
                            target_ref=None,
                            dynamic_coordinates=(cx, cy),
                            confidence=GroundingConfidence.STRONG,
                            rationale=f"Resolved visual target '{target_desc}' at dynamic coordinates ({int(cx)}, {int(cy)})",
                            is_ambiguous=False,
                            evidence={
                                "vision_provider": vis_res.data.get("provider", "vlm"),
                                "screenshot_id": vis_res.data.get("screenshot_id"),
                                "coordinates": [cx, cy],
                            },
                        )
                # Malformed or failed vision result evaluates truthfully to UNKNOWN/NONE
                return PerceptionResult(
                    method=PerceptionMethod.NONE,
                    element=None,
                    target_ref=None,
                    confidence=GroundingConfidence.NONE,
                    rationale=f"Vision fallback failed to locate '{target_desc}': {vis_res.error or 'Target not recognized visually'}",
                    is_ambiguous=False,
                    evidence={"vision_error": vis_res.error},
                )
            except Exception as e:
                logger.warning("Vision fallback encountered error: %s", e)
                return PerceptionResult(
                    method=PerceptionMethod.NONE,
                    element=None,
                    target_ref=None,
                    confidence=GroundingConfidence.NONE,
                    rationale=f"Vision provider error: {e}",
                    is_ambiguous=False,
                    evidence={"exception": str(e)},
                )

        # Neither Accessibility nor Vision could resolve
        return PerceptionResult(
            method=PerceptionMethod.NONE,
            element=None,
            target_ref=None,
            confidence=GroundingConfidence.NONE,
            rationale=ax_match.rationale or f"Target '{target_desc}' not found in current UI state.",
            is_ambiguous=False,
            evidence={"accessibility_candidates": ax_match.candidates_count},
        )


perception_pipeline = PerceptionPipeline()
