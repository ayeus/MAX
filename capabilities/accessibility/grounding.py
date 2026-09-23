"""Hierarchical Semantic UI element grounding system for resolving action targets on macOS."""

from __future__ import annotations
from enum import Enum
import re
from typing import Any, Optional
from pydantic import BaseModel, Field

from capabilities.accessibility.models import UIElement, ComputerState, TargetReference, TargetValidity


class GroundingConfidence(str, Enum):
    """Confidence level of semantic grounding resolution."""

    EXACT = "EXACT"
    STRONG = "STRONG"
    WEAK = "WEAK"
    NONE = "NONE"


class TargetConstraints(BaseModel):
    """Declarative constraints used to locate a semantic target UI element."""

    role: Optional[str] = None  # e.g., 'button', 'text_field', 'search', 'row', 'group', 'dialog'
    label: Optional[str] = None  # Text in title, accessibility description, or placeholder
    value: Optional[str] = None  # Desired or current text value
    identifier: Optional[str] = None  # Accessibility identifier
    child_label: Optional[str] = None  # Descendant text to match within a container (e.g. Row containing "John")
    scope_path: Optional[str] = None  # Restrict candidate search to subtree under this path
    scope_role: Optional[str] = None  # Restrict candidate search to subtree under an ancestor with this role (e.g. 'AXDialog')
    index: int = 0  # 0-indexed if multiple candidates match
    target_ref: Optional[TargetReference] = None  # Previously pinned target to re-validate


class GroundingMatch(BaseModel):
    """Result of resolving a target against the current computer UI state."""

    element: Optional[UIElement] = None
    target_ref: Optional[TargetReference] = None
    score: float = 0.0
    confidence: GroundingConfidence = GroundingConfidence.NONE
    rationale: str = ""
    candidates_count: int = 0
    is_ambiguous: bool = False
    alternative_labels: list[str] = Field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """Determines if the match is sufficiently grounded to execute an action."""
        return (
            not self.is_ambiguous
            and self.confidence in (GroundingConfidence.EXACT, GroundingConfidence.STRONG)
            and self.element is not None
        )


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
    "group": ["AXGroup", "AXRow", "AXCell"],
    "cell": ["AXCell", "AXRow"],
    "table": ["AXTable", "AXOutline"],
    "list": ["AXList", "AXOutline"],
    "dialog": ["AXDialog", "AXSheet", "AXWindow"],
    "sheet": ["AXSheet", "AXDialog"],
    "menu_item": ["AXMenuItem"],
    "window": ["AXWindow"],
}

CONTAINER_ROLES = {"AXRow", "AXGroup", "AXCell", "AXTable", "AXOutline", "AXList", "AXSplitGroup", "AXScrollArea"}


class SemanticUIGrounder:
    """Grounds intended action targets to concrete UI elements in the current computer state."""

    def validate_target_reference(
        self, target_ref: TargetReference, current_state: ComputerState
    ) -> tuple[bool, Optional[UIElement], str]:
        """Validate whether a previously created TargetReference is still valid in current_state.

        Returns (is_valid, matched_element, status_message).
        """
        if not target_ref or not current_state:
            return False, None, "STALE_EMPTY"

        status, el, reason = target_ref.validate_in(current_state)
        return status == TargetValidity.VALID, el, reason

    def ground(self, constraints: TargetConstraints, state: ComputerState) -> GroundingMatch:
        """Find the best matching UI element for the given constraints."""
        # 0. Check if re-validating a previously pinned TargetReference
        if constraints.target_ref:
            is_valid, el, status = self.validate_target_reference(constraints.target_ref, state)
            if is_valid and el:
                # Update snapshot_id to keep reference alive
                new_ref = TargetReference(
                    target_id=constraints.target_ref.target_id,
                    snapshot_id=state.observation_metadata.snapshot_id if state.observation_metadata else "",
                    process_id=state.active_application_pid,
                    application_name=state.active_application,
                    window_title=state.active_window_title,
                    path=el.path,
                    role=el.role,
                    title=el.title,
                    identifier=el.identifier,
                    description=el.description,
                    value=el.value,
                    parent_path=el.parent_path,
                    bounds=el.bounds,
                )
                return GroundingMatch(
                    element=el,
                    target_ref=new_ref,
                    score=1.0,
                    confidence=GroundingConfidence.EXACT,
                    rationale=f"Re-validated target reference ({status}): '{el.title or el.description}' ({el.role})",
                    candidates_count=1,
                    is_ambiguous=False,
                )
            else:
                # Reference is stale; must fall through and reground
                pass

        # 1. Determine candidate pool (Scoped Subtree vs Global Interactive Elements)
        candidates = self._get_candidate_elements(constraints, state)
        if not candidates:
            return GroundingMatch(
                element=None,
                score=0.0,
                confidence=GroundingConfidence.NONE,
                rationale=f"No elements available in current application '{state.active_application}'.",
                candidates_count=0,
                is_ambiguous=False,
            )

        target_roles = []
        if constraints.role:
            r_norm = constraints.role.strip().lower()
            target_roles = ROLE_ALIASES.get(r_norm, [constraints.role])

        target_label = (constraints.label or "").strip().lower()
        child_label = (constraints.child_label or "").strip().lower()
        target_tokens = set(re.findall(r"\w+", target_label)) if target_label else set()

        is_container_search = any(r in CONTAINER_ROLES for r in target_roles) or bool(child_label)

        scored_candidates: list[tuple[float, UIElement, str]] = []

        for el in candidates:
            score = 0.0
            reasons = []

            # A. Role matching
            has_role_match = False
            if target_roles:
                if el.role in target_roles or any(el.role.lower() == r.lower() for r in target_roles):
                    has_role_match = True
                    score += 0.60 if not target_label and not child_label else 0.30
                    reasons.append(f"role match ({el.role})")
                else:
                    score -= 0.25

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

            # B. Hierarchical Container-to-Child Relationship Matching
            has_child_match = False
            if is_container_search and (child_label or target_label):
                query = child_label or target_label
                child_found, child_desc, child_score = self._search_container_descendants(el, query)
                if child_found:
                    has_child_match = True
                    score += child_score
                    reasons.append(f"descendant match ({child_desc})")

            # C. Label / Title / Description matching
            has_label_match = False
            if target_label:
                if el_title and el_title == target_label:
                    score += 0.60
                    has_label_match = True
                    reasons.append("exact title match")
                elif el_title and target_label in el_title:
                    score += 0.45
                    has_label_match = True
                    reasons.append("title contains query")
                elif el_title and el_title in target_label:
                    score += 0.40
                    has_label_match = True
                    reasons.append("query contains title")

                if el_desc and target_label in el_desc:
                    score += 0.40
                    has_label_match = True
                    reasons.append("description matches query")

                if target_tokens:
                    el_tokens = set(re.findall(r"\w+", f"{el_title} {el_desc}"))
                    if el_tokens:
                        overlap = len(target_tokens & el_tokens) / len(target_tokens)
                        if overlap > 0.5:
                            score += 0.25 * overlap
                            has_label_match = True
                            reasons.append(f"token overlap ({overlap:.0%})")

                # If user specified a label, require either direct label match OR container descendant match
                if not has_label_match and not has_child_match:
                    continue

            # D. Value matching if specified
            if constraints.value and el_val:
                c_val = constraints.value.strip().lower()
                if c_val in el_val:
                    score += 0.20
                    reasons.append("value match")

            # E. Identifier matching
            if constraints.identifier and el.identifier:
                if constraints.identifier.lower() in el.identifier.lower():
                    score += 0.50
                    reasons.append("identifier match")

            # F. Focused input bonus
            if constraints.role in ("text_field", "input", "search", "text_area") and not target_label:
                if el.role in ("AXTextField", "AXTextArea", "AXSearchField"):
                    if el.is_focused:
                        score += 0.35
                        reasons.append("currently focused input")

            if score > 0.25:
                scored_candidates.append((score, el, ", ".join(reasons)))

        if not scored_candidates:
            alt_list = [f"{e.role}: {e.title or e.description}" for e in candidates[:5]]
            return GroundingMatch(
                element=None,
                score=0.0,
                confidence=GroundingConfidence.NONE,
                rationale=f"No matching UI elements found for label='{constraints.label}', role='{constraints.role}'.",
                candidates_count=0,
                is_ambiguous=False,
                alternative_labels=alt_list,
            )

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        best_score, best_elem, best_reason = scored_candidates[0]

        # Strict Ambiguity Check (Rule 5: Zero Blind Actions)
        if len(scored_candidates) > 1:
            second_score, second_elem, _ = scored_candidates[1]
            score_diff = abs(best_score - second_score)
            if score_diff < 0.08:
                # Check if elements are truly distinct and indistinguishable
                if (best_elem.title == second_elem.title and best_elem.role == second_elem.role) or best_score < 0.75:
                    return GroundingMatch(
                        element=None,
                        score=best_score,
                        confidence=GroundingConfidence.WEAK,
                        rationale=(
                            f"Ambiguous target: multiple candidates match with near-identical score "
                            f"(Candidate 1: {best_elem.role} '{best_elem.title or best_elem.description}' at {best_elem.path} "
                            f"vs Candidate 2: {second_elem.role} '{second_elem.title or second_elem.description}' at {second_elem.path}). "
                            f"Refusing blind action."
                        ),
                        candidates_count=len(scored_candidates),
                        is_ambiguous=True,
                        alternative_labels=[f"{e.role}: {e.title or e.description}" for _, e, _ in scored_candidates[:5]],
                    )

        if best_score >= 0.85:
            conf = GroundingConfidence.EXACT
        elif best_score >= 0.55:
            conf = GroundingConfidence.STRONG
        else:
            conf = GroundingConfidence.WEAK

        label_display = (
            best_elem.title
            if (best_elem.title and best_elem.title != "missing value")
            else (best_elem.description or best_elem.role)
        )

        target_ref = TargetReference(
            snapshot_id=state.observation_metadata.snapshot_id if state.observation_metadata else "",
            process_id=state.active_application_pid,
            application_name=state.active_application,
            window_title=state.active_window_title,
            path=best_elem.path,
            role=best_elem.role,
            title=best_elem.title,
            identifier=best_elem.identifier,
            description=best_elem.description,
            value=best_elem.value,
            parent_path=best_elem.parent_path,
            bounds=best_elem.bounds,
        )

        return GroundingMatch(
            element=best_elem,
            target_ref=target_ref,
            score=round(best_score, 2),
            confidence=conf,
            rationale=f"Resolved target '{label_display}' ({best_elem.role}) via {best_reason}",
            candidates_count=len(scored_candidates),
            is_ambiguous=False,
            alternative_labels=[f"{e.role}: {e.title or e.description}" for _, e, _ in scored_candidates[1:4]],
        )

    def _get_candidate_elements(self, constraints: TargetConstraints, state: ComputerState) -> list[UIElement]:
        """Collect the pool of elements to search based on scoping and container requirements."""
        # 1. Scoped to a specific path
        if constraints.scope_path and state.root_element:
            scope_root = state.root_element.find_by_path(constraints.scope_path)
            if scope_root:
                return scope_root.flatten()

        # 2. Scoped to an ancestor role (e.g. AXDialog or AXSheet)
        if constraints.scope_role and state.root_element:
            role_targets = ROLE_ALIASES.get(constraints.scope_role.lower(), [constraints.scope_role])
            for node in state.root_element.flatten():
                if node.role in role_targets or node.role.lower() in [r.lower() for r in role_targets]:
                    return node.flatten()

        # 3. If searching for container elements (e.g. AXRow, AXGroup, AXCell), search entire flattened tree
        if constraints.role:
            r_norm = constraints.role.strip().lower()
            target_roles = ROLE_ALIASES.get(r_norm, [constraints.role])
            if any(r in CONTAINER_ROLES for r in target_roles):
                if state.root_element:
                    return state.root_element.flatten()

        # 4. Default: search all interactive elements plus root descendants if available
        if state.root_element:
            all_nodes = state.root_element.flatten()
            return all_nodes if len(all_nodes) > len(state.interactive_elements) else state.interactive_elements

        return state.interactive_elements

    def _search_container_descendants(self, container: UIElement, query: str) -> tuple[bool, str, float]:
        """Search descendants of a container for matching semantic label.

        Returns (found, matching_description, score_bonus).
        """
        if not container.children:
            return False, "", 0.0

        q = query.strip().lower()
        descendants = container.flatten()[1:]  # Exclude container itself

        for d in descendants:
            d_title = (d.title or "").strip().lower()
            d_desc = (d.description or "").strip().lower()
            d_val = (d.value or "").strip().lower()

            if d_title and d_title == q:
                return True, f"exact child title '{d.title}' in {d.role}", 0.65
            if d_title and q in d_title:
                return True, f"child title contains '{query}' in {d.role}", 0.50
            if d_desc and q in d_desc:
                return True, f"child description contains '{query}' in {d.role}", 0.45
            if d_val and q in d_val:
                return True, f"child value contains '{query}' in {d.role}", 0.45

        return False, "", 0.0


ui_grounder = SemanticUIGrounder()
