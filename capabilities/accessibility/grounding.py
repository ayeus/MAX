"""Semantic UI element grounding system for resolving action targets on macOS."""

from enum import Enum
import re
from typing import Any, Optional
from pydantic import BaseModel, Field
from capabilities.accessibility.models import UIElement, ComputerState


class GroundingConfidence(str, Enum):
    EXACT = "EXACT"
    STRONG = "STRONG"
    WEAK = "WEAK"
    NONE = "NONE"


class TargetConstraints(BaseModel):
    """Declarative constraints used to locate a semantic target UI element."""

    role: Optional[str] = None  # e.g., 'button', 'text_field', 'search', 'tab', 'menu_item'
    label: Optional[str] = None  # Text in title, accessibility description, or placeholder
    value: Optional[str] = None  # Desired or current text value
    identifier: Optional[str] = None  # Accessibility identifier
    index: int = 0  # 0-indexed if multiple candidates match


class GroundingMatch(BaseModel):
    """Result of resolving a target against the current computer UI state."""

    element: Optional[UIElement] = None
    score: float = 0.0
    confidence: GroundingConfidence = GroundingConfidence.NONE
    rationale: str = ""
    candidates_count: int = 0
    alternative_labels: list[str] = Field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """Determines if the match is sufficiently grounded to execute an action."""
        return self.confidence in (GroundingConfidence.EXACT, GroundingConfidence.STRONG) and self.element is not None


# Generic role aliases
ROLE_ALIASES: dict[str, list[str]] = {
    "button": ["AXButton", "AXPopUpButton"],
    "text_field": ["AXTextField", "AXTextArea", "AXSearchField"],
    "input": ["AXTextField", "AXTextArea", "AXSearchField"],
    "text_area": ["AXTextArea", "AXTextField"],
    "search": ["AXSearchField", "AXTextField"],
    "popup_button": ["AXPopUpButton"],
    "checkbox": ["AXCheckBox"],
    "radio": ["AXRadioButton"],
    "tab": ["AXTabGroup", "AXRadioButton"],
    "link": ["AXLink"],
    "text": ["AXStaticText", "AXTextField"],
    "row": ["AXRow"],
    "menu_item": ["AXMenuItem"],
}


class SemanticUIGrounder:
    """Grounds intended action targets to concrete UI elements in the current computer state."""

    def ground(self, constraints: TargetConstraints, state: ComputerState) -> GroundingMatch:
        """Find the best matching UI element for the given constraints."""
        if not state.interactive_elements:
            return GroundingMatch(
                element=None,
                score=0.0,
                confidence=GroundingConfidence.NONE,
                rationale=f"No interactive elements available in current application '{state.active_application}'.",
                candidates_count=0,
            )

        target_roles = []
        if constraints.role:
            r_norm = constraints.role.strip().lower()
            target_roles = ROLE_ALIASES.get(r_norm, [constraints.role])

        target_label = (constraints.label or "").strip().lower()
        target_tokens = set(re.findall(r"\w+", target_label)) if target_label else set()

        scored_candidates: list[tuple[float, UIElement, str]] = []

        for el in state.interactive_elements:
            score = 0.0
            reasons = []

            # 1. Role matching
            has_role_match = False
            if target_roles:
                if el.role in target_roles or el.role.lower() in [r.lower() for r in target_roles]:
                    has_role_match = True
                    score += 0.60 if not target_label else 0.30
                    reasons.append(f"role match ({el.role})")
                else:
                    score -= 0.20

            # 2. Label / Title / Description matching
            el_title = (el.title or "").strip().lower()
            el_desc = (el.description or "").strip().lower()
            el_val = (el.value or "").strip().lower()

            # Clean out common macOS placeholder artifact
            if el_title == "missing value":
                el_title = ""
            if el_desc == "missing value":
                el_desc = ""
            if el_val == "missing value":
                el_val = ""

            has_label_match = False
            if target_label:
                # Exact title match
                if el_title and el_title == target_label:
                    score += 0.60
                    has_label_match = True
                    reasons.append("exact title match")
                # Substring title match
                elif el_title and target_label in el_title:
                    score += 0.45
                    has_label_match = True
                    reasons.append("title contains query")
                elif el_title and el_title in target_label:
                    score += 0.40
                    has_label_match = True
                    reasons.append("query contains title")

                # Description / placeholder match
                if el_desc and target_label in el_desc:
                    score += 0.40
                    has_label_match = True
                    reasons.append("description matches query")

                # Token overlap
                if target_tokens:
                    el_tokens = set(re.findall(r"\w+", f"{el_title} {el_desc}"))
                    if el_tokens:
                        overlap = len(target_tokens & el_tokens) / len(target_tokens)
                        if overlap > 0.5:
                            score += 0.25 * overlap
                            has_label_match = True
                            reasons.append(f"token overlap ({overlap:.0%})")

                # If user specified a label, an element with NO label match at all must not be considered a match
                if not has_label_match:
                    continue

            # 3. Value matching if specified
            if constraints.value and el_val:
                c_val = constraints.value.strip().lower()
                if c_val in el_val:
                    score += 0.20
                    reasons.append("value match")

            # 4. Identifier matching
            if constraints.identifier and el.identifier:
                if constraints.identifier.lower() in el.identifier.lower():
                    score += 0.50
                    reasons.append("identifier match")

            # 5. Default text field heuristic if user specifically wants a text input
            if constraints.role in ("text_field", "input", "search", "text_area") and not target_label:
                if el.role in ("AXTextField", "AXTextArea", "AXSearchField"):
                    if el.is_focused:
                        score += 0.25
                        reasons.append("currently focused input")

            if score > 0.25:
                scored_candidates.append((score, el, ", ".join(reasons)))

        if not scored_candidates:
            return GroundingMatch(
                element=None,
                score=0.0,
                confidence=GroundingConfidence.NONE,
                rationale=f"No matching UI elements found for label='{constraints.label}', role='{constraints.role}'.",
                candidates_count=0,
                alternative_labels=[f"{e.role}: {e.title or e.description}" for e in state.interactive_elements[:5]],
            )

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        best_score, best_elem, best_reason = scored_candidates[0]

        # Check for ambiguity among top candidates
        if len(scored_candidates) > 1:
            second_score, second_elem, _ = scored_candidates[1]
            if abs(best_score - second_score) < 0.05:
                # If tied with same role and title/label, or scores are too close and low
                if (best_elem.title == second_elem.title and best_elem.role == second_elem.role) or best_score < 0.70:
                    return GroundingMatch(
                        element=None,
                        score=best_score,
                        confidence=GroundingConfidence.WEAK,
                        rationale=f"Ambiguous target: multiple similar elements match ({best_elem.role}: '{best_elem.title or best_elem.description}' vs {second_elem.role}: '{second_elem.title or second_elem.description}'). Refusing blind action.",
                        candidates_count=len(scored_candidates),
                        alternative_labels=[f"{e.role}: {e.title or e.description}" for _, e, _ in scored_candidates[:5]],
                    )

        if best_score >= 0.85:
            conf = GroundingConfidence.EXACT
        elif best_score >= 0.55:
            conf = GroundingConfidence.STRONG
        else:
            conf = GroundingConfidence.WEAK

        label_display = best_elem.title if (best_elem.title and best_elem.title != "missing value") else (best_elem.description or best_elem.role)
        return GroundingMatch(
            element=best_elem,
            score=round(best_score, 2),
            confidence=conf,
            rationale=f"Resolved target '{label_display}' ({best_elem.role}) via {best_reason}",
            candidates_count=len(scored_candidates),
            alternative_labels=[f"{e.role}: {e.title or e.description}" for _, e, _ in scored_candidates[1:4]],
        )


ui_grounder = SemanticUIGrounder()
