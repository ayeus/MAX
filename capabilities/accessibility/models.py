"""Data models for macOS GUI elements and ComputerState."""

from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class UIElement(BaseModel):
    """Semantic representation of an accessible macOS UI control."""

    role: str = "AXUnknown"  # e.g., AXButton, AXTextField, AXTextArea, AXStaticText, AXPopUpButton, AXRow, AXTabGroup
    title: str = ""  # Accessible title / name
    value: Optional[str] = None  # Current text value or state
    description: Optional[str] = None  # Accessibility description or placeholder
    identifier: Optional[str] = None  # Automation or unique ID
    bounds: Optional[dict[str, float]] = None  # {"x": ..., "y": ..., "width": ..., "height": ...}
    is_focused: bool = False
    is_enabled: bool = True
    actions: list[str] = Field(default_factory=list)  # e.g., ["AXPress", "AXShowMenu"]
    path: str = ""  # Hierarchical address in tree
    subrole: Optional[str] = None

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
        summary = {"role": self.role}
        if self.title:
            summary["title"] = self.title
        if self.description:
            summary["description"] = self.description
        if self.value:
            summary["value"] = self.value[:80] + ("..." if len(self.value) > 80 else "")
        if self.is_focused:
            summary["focused"] = True
        if self.actions:
            summary["actions"] = self.actions
        return summary


class ComputerState(BaseModel):
    """Structured observation of the computer's current GUI state."""

    active_application: str
    active_window_title: str = ""
    active_window_bounds: Optional[dict[str, float]] = None
    visible_windows: list[str] = Field(default_factory=list)
    focused_element: Optional[UIElement] = None
    interactive_elements: list[UIElement] = Field(default_factory=list)
    clipboard_preview: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_elements_by_role(self, role: str) -> list[UIElement]:
        """Filter interactive elements by AXRole."""
        r = role.lower()
        return [el for el in self.interactive_elements if el.role.lower() == r]

    def to_compact_prompt_summary(self, max_elements: int = 25) -> dict[str, Any]:
        """Generate compact JSON-serializable dictionary for LLM context."""
        return {
            "active_application": self.active_application,
            "active_window": self.active_window_title,
            "visible_windows": self.visible_windows[:5],
            "focused_element": self.focused_element.to_summary_dict() if self.focused_element else None,
            "interactive_controls": [el.to_summary_dict() for el in self.interactive_elements[:max_elements]],
            "total_controls_detected": len(self.interactive_elements),
            "clipboard_preview": self.clipboard_preview,
        }
