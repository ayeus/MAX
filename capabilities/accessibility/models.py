"""Data models for macOS GUI elements and ComputerState."""

from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field


class AccessibilityHealthStatus(str, Enum):
    """Accessibility health and permission status of macOS environment."""

    ACCESSIBILITY_AVAILABLE = "ACCESSIBILITY_AVAILABLE"
    ACCESSIBILITY_DENIED = "ACCESSIBILITY_DENIED"
    ACCESSIBILITY_UNAVAILABLE = "ACCESSIBILITY_UNAVAILABLE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class WindowState(BaseModel):
    """Detailed observation of an application window."""

    title: str = ""
    role: str = "AXWindow"
    subrole: Optional[str] = None  # e.g., AXStandardWindow, AXDialog
    is_focused: bool = False
    is_minimized: bool = False
    is_modal: bool = False
    bounds: Optional[dict[str, float]] = None  # {"x": ..., "y": ..., "width": ..., "height": ...}
    pid: Optional[int] = None


class ObservationMetadata(BaseModel):
    """Diagnostic metadata describing an observation snapshot."""

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}_{int(datetime.now(timezone.utc).timestamp())}")
    captured_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    latency_ms: float = 0.0
    accessibility_status: AccessibilityHealthStatus = AccessibilityHealthStatus.UNKNOWN
    backend: str = "native_swift"
    is_truncated: bool = False
    truncated_by: Optional[str] = None
    traversal_stats: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class UIElement(BaseModel):
    """Semantic representation of an accessible macOS UI control."""

    role: str = "AXUnknown"  # e.g., AXButton, AXTextField, AXTextArea, AXStaticText, AXPopUpButton, AXRow, AXTabGroup
    subrole: Optional[str] = None  # e.g., AXCloseButton, AXSearchField, AXSecureTextField
    title: str = ""  # Accessible title / name
    value: Optional[str] = None  # Current text value or state
    description: Optional[str] = None  # Accessibility description or placeholder
    identifier: Optional[str] = None  # Automation or unique ID
    bounds: Optional[dict[str, float]] = None  # {"x": ..., "y": ..., "width": ..., "height": ...}
    is_focused: bool = False
    is_enabled: Optional[bool] = None
    is_selected: Optional[bool] = None
    actions: list[str] = Field(default_factory=list)  # e.g., ["AXPress", "AXShowMenu"]
    path: str = ""  # Hierarchical address in tree (e.g. AXWindow[0]/AXGroup[1]/AXButton[0])
    parent_path: Optional[str] = None
    children: list[UIElement] = Field(default_factory=list)

    def matches_query(self, query: str) -> bool:
        """Check if this element's text attributes match a search query."""
        q = query.strip().lower()
        if not q:
            return False
        if q in (self.title or "").lower():
            return True
        if q in (self.description or "").lower():
            return True
        if q in (self.value or "").lower():
            return True
        if q in (self.identifier or "").lower():
            return True
        return False

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact representation for LLM prompt context."""
        summary: dict[str, Any] = {"role": self.role}
        if self.subrole:
            summary["subrole"] = self.subrole
        if self.title:
            summary["title"] = self.title
        if self.description:
            summary["description"] = self.description
        if self.value:
            summary["value"] = self.value[:80] + ("..." if len(self.value) > 80 else "")
        if self.identifier:
            summary["identifier"] = self.identifier
        if self.is_focused:
            summary["focused"] = True
        if self.is_selected:
            summary["selected"] = True
        if not self.is_enabled:
            summary["enabled"] = False
        if self.actions:
            summary["actions"] = self.actions
        if self.path:
            summary["path"] = self.path
        if self.bounds:
            summary["bounds"] = self.bounds
        return summary

    def flatten(self) -> list[UIElement]:
        """Flatten element and all its recursive descendants into a single list."""
        nodes: list[UIElement] = [self]
        for child in self.children:
            nodes.extend(child.flatten())
        return nodes

    def find_by_path(self, target_path: str) -> Optional[UIElement]:
        """Locate element with exact matching hierarchical path."""
        if self.path == target_path:
            return self
        for child in self.children:
            found = child.find_by_path(target_path)
            if found:
                return found
        return None


# Rebuild model to support recursive type annotation
UIElement.model_rebuild()


class ComputerState(BaseModel):
    """Structured observation of the computer's current GUI state."""

    active_application: str
    active_application_pid: Optional[int] = None
    active_window_title: str = ""
    active_window_bounds: Optional[dict[str, float]] = None
    active_window: Optional[WindowState] = None
    windows: list[WindowState] = Field(default_factory=list)
    visible_windows: list[str] = Field(default_factory=list)
    focused_element: Optional[UIElement] = None
    root_element: Optional[UIElement] = None
    interactive_elements: list[UIElement] = Field(default_factory=list)
    clipboard_preview: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    observation_metadata: ObservationMetadata = Field(default_factory=ObservationMetadata)

    def get_elements_by_role(self, role: str) -> list[UIElement]:
        """Filter interactive elements by AXRole."""
        r = role.lower()
        return [el for el in self.interactive_elements if el.role.lower() == r]

    def to_compact_prompt_summary(self, max_elements: int = 25) -> dict[str, Any]:
        """Generate compact JSON-serializable dictionary for LLM context."""
        summary = {
            "active_application": self.active_application,
            "active_application_pid": self.active_application_pid,
            "active_window": self.active_window_title,
            "visible_windows": self.visible_windows[:5] if self.visible_windows else [w.title for w in self.windows[:5] if w.title],
            "focused_element": self.focused_element.to_summary_dict() if self.focused_element else None,
            "interactive_controls": [el.to_summary_dict() for el in self.interactive_elements[:max_elements]],
            "total_controls_detected": len(self.interactive_elements),
            "clipboard_preview": self.clipboard_preview,
            "observation_metadata": {
                "snapshot_id": self.observation_metadata.snapshot_id,
                "latency_ms": self.observation_metadata.latency_ms,
                "accessibility_status": self.observation_metadata.accessibility_status.value,
                "backend": self.observation_metadata.backend,
            },
        }
        return summary

    def compute_delta(self, other: ComputerState) -> dict[str, Any]:
        """Compute semantic difference between this state and a subsequent state.

        Useful for closed-loop verification (e.g. window changed, focus shifted,
        value updated, new modal appeared).
        """
        app_changed = self.active_application != other.active_application
        window_changed = self.active_window_title != other.active_window_title

        prev_focus_path = self.focused_element.path if self.focused_element else None
        curr_focus_path = other.focused_element.path if other.focused_element else None
        focus_changed = prev_focus_path != curr_focus_path

        # Compare values of elements by path
        prev_values = {el.path: el.value for el in self.interactive_elements if el.path and el.value is not None}
        curr_values = {el.path: el.value for el in other.interactive_elements if el.path and el.value is not None}
        value_changes = {}
        for path, val in curr_values.items():
            if path in prev_values and prev_values[path] != val:
                value_changes[path] = {"old": prev_values[path], "new": val}

        # Compare selection of elements by path
        prev_selected = {el.path for el in self.interactive_elements if el.path and el.is_selected}
        curr_selected = {el.path for el in other.interactive_elements if el.path and el.is_selected}

        # Count added / removed interactive controls
        prev_paths = {el.path for el in self.interactive_elements if el.path}
        curr_paths = {el.path for el in other.interactive_elements if el.path}

        return {
            "application_changed": app_changed,
            "previous_application": self.active_application,
            "current_application": other.active_application,
            "window_changed": window_changed,
            "previous_window": self.active_window_title,
            "current_window": other.active_window_title,
            "focus_changed": focus_changed,
            "previous_focused_path": prev_focus_path,
            "current_focused_path": curr_focus_path,
            "value_changes": value_changes,
            "new_selected": list(curr_selected - prev_selected),
            "unselected": list(prev_selected - curr_selected),
            "added_controls_count": len(curr_paths - prev_paths),
            "removed_controls_count": len(prev_paths - curr_paths),
        }


class TargetValidity(str, Enum):
    """Validation outcome for a TargetReference against a ComputerState."""

    VALID = "VALID"
    AMBIGUOUS = "AMBIGUOUS"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class TargetReference(BaseModel):
    """Stable semantic reference to a grounded UI element tied to an observation snapshot."""

    target_id: str = Field(default_factory=lambda: f"tgt_{uuid.uuid4().hex[:8]}")
    snapshot_id: str
    process_id: Optional[int] = None
    application_name: Optional[str] = None
    window_title: Optional[str] = None
    path: str
    role: str
    title: Optional[str] = None
    identifier: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None
    parent_path: Optional[str] = None
    ancestor_roles: list[str] = Field(default_factory=list)
    bounds: Optional[dict[str, float]] = None
    created_at: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def validate_in(self, state: ComputerState) -> tuple[TargetValidity, Optional[UIElement], str]:
        """Validate whether this TargetReference safely identifies a unique UIElement in state.

        Follows an explicit validation hierarchy:
        1. State inspectability (if None or denied -> UNKNOWN)
        2. Application/process identity
        3. Identity hierarchy matching:
           Level A: Native Accessibility Identifier (if known)
           Level B: Semantic Path
           Level C: Role, Title, Description, Value, Parent/Ancestor Context
        4. Plausibility / Ambiguity check:
           If multiple elements match with near-identical evidence -> AMBIGUOUS
        5. Single unique match -> VALID
        6. Missing or mismatch -> STALE
        """
        if not state:
            return TargetValidity.UNKNOWN, None, "State is None; cannot inspect target."

        if state.observation_metadata and state.observation_metadata.accessibility_status in (
            AccessibilityHealthStatus.ACCESSIBILITY_DENIED,
            AccessibilityHealthStatus.ACCESSIBILITY_UNAVAILABLE,
        ):
            return TargetValidity.UNKNOWN, None, f"Accessibility unavailable ({state.observation_metadata.accessibility_status.value})."

        all_elements = state.root_element.flatten() if state.root_element else state.interactive_elements
        if not all_elements:
            return TargetValidity.STALE, None, "No elements present in computer state."

        # Level A: Lookup by path first
        path_match: Optional[UIElement] = None
        if state.root_element:
            path_match = state.root_element.find_by_path(self.path)
        if not path_match:
            for cand in state.interactive_elements:
                if cand.path == self.path:
                    path_match = cand
                    break

        if path_match:
            role_matches = path_match.role.lower() == self.role.lower()
            title_matches = True
            if self.title and path_match.title:
                title_matches = self.title.strip().lower() == path_match.title.strip().lower()
            id_matches = True
            if self.identifier and path_match.identifier:
                id_matches = self.identifier == path_match.identifier

            if role_matches and title_matches and id_matches:
                # Ambiguity check: are there multiple elements with the exact same title & role in current state?
                if self.title and not self.identifier:
                    duplicates = [
                        el for el in all_elements
                        if el.role.lower() == self.role.lower()
                        and el.title and el.title.strip().lower() == self.title.strip().lower()
                    ]
                    if len(duplicates) > 1:
                        if self.parent_path:
                            same_parent = [d for d in duplicates if d.parent_path == self.parent_path]
                            if len(same_parent) == 1:
                                return TargetValidity.VALID, same_parent[0], "Verified uniquely via parent context."
                            elif len(same_parent) > 1:
                                return TargetValidity.AMBIGUOUS, None, f"Ambiguous: multiple identical elements ({len(same_parent)}) in parent '{self.parent_path}'."
                        return TargetValidity.AMBIGUOUS, None, f"Ambiguous: {len(duplicates)} matching '{self.role}' elements with title '{self.title}'."

                return TargetValidity.VALID, path_match, "Verified uniquely via semantic path and attributes."

        # Level B: Try matching by native identifier
        if self.identifier:
            id_candidates = [el for el in all_elements if el.identifier == self.identifier and el.role.lower() == self.role.lower()]
            if len(id_candidates) == 1:
                return TargetValidity.VALID, id_candidates[0], f"Verified uniquely via native identifier '{self.identifier}'."
            elif len(id_candidates) > 1:
                return TargetValidity.AMBIGUOUS, None, f"Ambiguous: multiple elements share identifier '{self.identifier}'."

        # Level C: Fallback search by title + role + parent context
        if self.title:
            matching = [
                el for el in all_elements
                if el.role.lower() == self.role.lower()
                and el.title and el.title.strip().lower() == self.title.strip().lower()
            ]
            if len(matching) == 1:
                return TargetValidity.VALID, matching[0], f"Verified uniquely via title '{self.title}'."
            elif len(matching) > 1:
                if self.parent_path:
                    parent_matching = [m for m in matching if m.parent_path == self.parent_path]
                    if len(parent_matching) == 1:
                        return TargetValidity.VALID, parent_matching[0], "Verified uniquely via title and parent context."
                return TargetValidity.AMBIGUOUS, None, f"Ambiguous: {len(matching)} candidates match title '{self.title}'."

        return TargetValidity.STALE, None, f"STALE_NOT_FOUND: Element at path '{self.path}' ({self.role}) is no longer safely identifiable."

    def is_valid_in(self, state: ComputerState) -> bool:
        """Check if target remains valid in the given ComputerState."""
        status, _, _ = self.validate_in(state)
        return status == TargetValidity.VALID

