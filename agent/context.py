"""Context assembler for MAX agent planning with task-relevant minimization."""

from pydantic import BaseModel, Field
from typing import Any
from .observer import observer, EnvironmentObservation
from memory.preferences import preference_manager
from memory.memories import memory_manager


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
        if self.observation.ui_summary and self.observation.ui_summary.get("interactive_controls"):
            data["interactive_controls"] = self.observation.ui_summary["interactive_controls"]
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
