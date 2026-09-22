"""Context assembler for MAX agent planning."""

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
        """Convert context to format suitable for LLM prompt."""
        return {
            "current_directory": self.observation.current_directory,
            "active_application": self.observation.active_application,
            "running_processes_sample": self.observation.recent_processes,
            "clipboard_preview": self.observation.clipboard_preview,
            "user_preferences": self.preferences,
            "user_memories": self.memories,
        }


def assemble_context(recent_history: list[dict[str, Any]] | None = None) -> AgentContext:
    """Gather live context from the system and persistent storage."""
    obs = observer.observe()
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
