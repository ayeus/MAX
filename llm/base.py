"""Abstract LLM Provider interface for MAX."""

from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any


class LLMMessage(BaseModel):
    role: str
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    total_duration_ms: float = 0.0
    prompt_eval_count: int = 0
    eval_count: int = 0
    raw_response: dict[str, Any] = {}


class LLMProvider(ABC):
    """Abstract interface for local and remote LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_format: bool = False,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Generate a completion from a single prompt."""
        pass

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        json_format: bool = False,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Generate a response from a multi-turn message sequence."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is reachable and active."""
        pass
