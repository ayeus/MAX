"""Capability-aware model management and fallback resolution for MAX."""

from enum import Enum
import re
from typing import Optional
from app.config import settings
from .base import LLMProvider
from .ollama import OllamaProvider


class ModelCapability(str, Enum):
    REASONING = "reasoning"
    FAST_REASONING = "fast_reasoning"
    VISION = "vision"
    EMBEDDING = "embedding"


VISION_PATTERNS = [r"moondream", r"llava", r"bakllava", r"minicpm-v", r"qwen2-vl", r"vision", r"internvl"]
EMBEDDING_PATTERNS = [r"embed", r"bge", r"nomic", r"bert", r"gte"]
FAST_PATTERNS = [r":0\.5b", r":1b", r":1\.5b", r":3b", r"phi", r"tinyllama", r"smollm"]


def classify_model(model_name: str) -> set[ModelCapability]:
    """Classify model capabilities based on model naming conventions."""
    name = model_name.lower()
    caps = set()

    for p in EMBEDDING_PATTERNS:
        if re.search(p, name):
            caps.add(ModelCapability.EMBEDDING)
            return caps  # Embedding models are purely for embeddings

    for p in VISION_PATTERNS:
        if re.search(p, name):
            caps.add(ModelCapability.VISION)

    for p in FAST_PATTERNS:
        if re.search(p, name):
            caps.add(ModelCapability.FAST_REASONING)

    # General instruction/reasoning models
    caps.add(ModelCapability.REASONING)
    return caps


class ModelManager:
    """Manages active LLM provider and capability-aware model fallback selection."""

    def __init__(self, provider: LLMProvider | None = None):
        self._provider = provider or OllamaProvider()

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    def set_model(self, model_name: str) -> None:
        """Switch the active reasoning model."""
        if isinstance(self._provider, OllamaProvider):
            self._provider.model_name = model_name

    def verify_and_resolve_model(self, capability: ModelCapability = ModelCapability.REASONING) -> Optional[str]:
        """Capability-aware resolution: Never blindly pick models[0].

        Ensures embedding models are never selected for reasoning or chat,
        and vision-capable models are selected when vision is requested.
        Fails closed (returns None) if requested specialized capability (e.g. vision) is absent.
        """
        if isinstance(self._provider, OllamaProvider) or hasattr(self._provider, "list_models"):
            models = self._provider.list_models()
            if not models:
                return settings.reasoning_model if capability in (ModelCapability.REASONING, ModelCapability.FAST_REASONING) else None

            # 1. If capability is REASONING or FAST_REASONING, check preferred/current model
            if capability in (ModelCapability.REASONING, ModelCapability.FAST_REASONING):
                current = self._provider.model_name
                for m in models:
                    if m == current or m.startswith(current + ":") or current.startswith(m.split(":")[0]):
                        m_caps = classify_model(m)
                        if capability in m_caps and ModelCapability.EMBEDDING not in m_caps:
                            return m

            # 2. Find candidate models with matching capability
            candidates = []
            for m in models:
                m_caps = classify_model(m)
                if capability in m_caps:
                    # Do not choose an embedding model for reasoning
                    if capability == ModelCapability.REASONING and ModelCapability.EMBEDDING in m_caps:
                        continue
                    candidates.append(m)

            if candidates:
                fallback = candidates[0]
                if capability in (ModelCapability.REASONING, ModelCapability.FAST_REASONING):
                    self._provider.model_name = fallback
                return fallback

            # 3. If no exact capability match, fallback to any non-embedding model ONLY for reasoning
            if capability in (ModelCapability.REASONING, ModelCapability.FAST_REASONING):
                non_embedding = [m for m in models if ModelCapability.EMBEDDING not in classify_model(m)]
                if non_embedding:
                    fallback = non_embedding[0]
                    self._provider.model_name = fallback
                    return fallback
                return settings.reasoning_model

            # For VISION or EMBEDDING, fail closed if no matching capability is found
            return None

        return settings.reasoning_model if capability in (ModelCapability.REASONING, ModelCapability.FAST_REASONING) else None


# Global instance
model_manager = ModelManager()
