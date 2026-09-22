"""Model management and fallback resolution for MAX."""

from app.config import settings
from .base import LLMProvider
from .ollama import OllamaProvider


class ModelManager:
    """Manages active LLM provider and model fallback selection."""

    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or OllamaProvider()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    def set_model(self, model_name: str) -> None:
        """Switch the active reasoning model."""
        if isinstance(self._provider, OllamaProvider):
            self._provider.model_name = model_name

    def verify_and_resolve_model(self) -> str:
        """Check if configured model is present; if not, pick the best available local model."""
        if isinstance(self._provider, OllamaProvider):
            models = self._provider.list_models()
            current = self._provider.model_name
            # If current exact match or with :latest
            for m in models:
                if m == current or m.startswith(current + ":") or current.startswith(m.split(":")[0]):
                    return m
            # If current not found, fallback to any available instruction model
            if models:
                fallback = models[0]
                self._provider.model_name = fallback
                return fallback
        return settings.reasoning_model


# Global instance
model_manager = ModelManager()
