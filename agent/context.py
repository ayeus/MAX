"""Context assembler for MAX agent planning with task-relevant minimization."""

from typing import Any
from pydantic import BaseModel, Field
from memory.memories import memory_manager
from memory.preferences import preference_manager
from .observer import EnvironmentObservation, observer


class AgentContext(BaseModel):
    observation: EnvironmentObservation
    preferences: dict[str, str] = Field(default_factory=dict)
    memories: list[dict[str, str]] = Field(default_factory=list)
    recent_history: list[dict[str, Any]] = Field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        """Convert context to format suitable for LLM prompt, omitting empty/irrelevant fields."""
        data: dict[str, Any] = {
            "current_directory": self.observation.current_directory,
            "active_application": self.observation.active_application,
        }
        if self.observation.active_window:
            data["active_window"] = self.observation.active_window
        if self.observation.ui_summary:
            if self.observation.ui_summary.get("focused_element"):
                data["focused_element"] = self.observation.ui_summary["focused_element"]
            if self.observation.ui_summary.get("interactive_controls"):
                data["interactive_controls"] = self.observation.ui_summary["interactive_controls"]
            if self.observation.ui_summary.get("visible_windows"):
                data["visible_windows"] = self.observation.ui_summary["visible_windows"]
        if self.observation.recent_processes:
            data["running_processes_sample"] = self.observation.recent_processes[:10]
        if self.observation.clipboard_preview:
            data["clipboard_preview"] = self.observation.clipboard_preview
        if self.preferences:
            data["user_preferences"] = self.preferences
        if self.memories:
            data["user_memories"] = self.memories
        return data


def assemble_context(
    recent_history: list[dict[str, Any]] | None = None,
    fast: bool = True,
) -> AgentContext:
    """Gather live context from the system with task-relevant minimization."""
    obs = observer.observe(fast=fast)
    prefs = preference_manager.list_preferences()
    mems = [
        {"key": m.key, "content": m.content, "category": m.category}
        for m in memory_manager.list_memories()
    ]
    return AgentContext(
        observation=obs,
        preferences=prefs,
        memories=mems,
        recent_history=recent_history or [],
    )
