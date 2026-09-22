"""Vision provider abstraction and Ollama vision integration for MAX."""

from abc import ABC, abstractmethod
import base64
import json
from pathlib import Path
from pydantic import BaseModel, Field
import urllib.error
import urllib.request
from typing import Optional
from app.config import settings


class VisionResponse(BaseModel):
    success: bool
    text: str
    model: str
    duration_ms: float = 0.0
    error: Optional[str] = None


class VisionProvider(ABC):
    """Abstract interface for local vision-language model providers."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the vision provider and model are available."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the active vision model identifier."""
        pass

    @abstractmethod
    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        system: Optional[str] = None,
        json_format: bool = False,
    ) -> VisionResponse:
        """Analyze an image using the local vision model."""
        pass


KNOWN_VISION_MODELS = [
    "moondream",
    "moondream:latest",
    "llama3.2-vision",
    "llava",
    "qwen2-vl",
    "bakllava",
    "minicpm-v",
]


class OllamaVisionProvider(VisionProvider):
    """Local Ollama vision provider communicating with local Ollama daemon."""

    def __init__(
        self,
        base_url: str = settings.ollama_base_url,
        preferred_model: Optional[str] = None,
        timeout: float = 45.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.preferred_model = preferred_model or settings.vision_model
        self.timeout = timeout
        self._resolved_model: Optional[str] = None

    def _get_installed_models(self) -> list[str]:
        """Query installed models from Ollama."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def _resolve_model(self) -> Optional[str]:
        """Discover an installed vision-capable model using central ModelManager."""
        installed = self._get_installed_models()
        if not installed:
            return None

        # 1. Check if preferred_model is installed
        if self.preferred_model:
            for m in installed:
                if m == self.preferred_model or m.startswith(self.preferred_model.split(":")[0]):
                    return m

        # 2. Delegate to central ModelManager
        from llm.model_manager import model_manager, ModelCapability
        return model_manager.verify_and_resolve_model(ModelCapability.VISION)

    def is_available(self) -> bool:
        """Verify Ollama is reachable and a vision-capable model is installed."""
        return self._resolve_model() is not None

    def get_model_name(self) -> str:
        """Return resolved vision model name."""
        resolved = self._resolve_model()
        return resolved or self.preferred_model

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        system: Optional[str] = None,
        json_format: bool = False,
    ) -> VisionResponse:
        """Send base64-encoded image to local Ollama vision model."""
        resolved = self._resolve_model()
        if not resolved:
            return VisionResponse(
                success=False,
                text="",
                model=self.preferred_model,
                error=(
                    "Vision model unavailable. No installed vision model found in local Ollama.\n"
                    "Prerequisite: Run 'ollama pull moondream' or configure MAX_VISION_MODEL with an installed vision model."
                ),
            )

        img_file = Path(image_path)
        if not img_file.exists() or img_file.stat().st_size == 0:
            return VisionResponse(
                success=False,
                text="",
                model=resolved,
                error=f"Image file does not exist or is empty: {image_path}",
            )

        import time
        start_time = time.time()

        try:
            with open(img_file, "rb") as f:
                b64_image = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "model": resolved,
                "prompt": prompt,
                "images": [b64_image],
                "stream": False,
                "options": {
                    "temperature": 0.1,
                },
            }
            if system:
                payload["system"] = system
            if json_format:
                payload["format"] = "json"

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode("utf-8"))
                    text = result.get("response", "").strip()
                    duration_ms = (time.time() - start_time) * 1000.0
                    return VisionResponse(
                        success=True,
                        text=text,
                        model=resolved,
                        duration_ms=duration_ms,
                    )
                else:
                    return VisionResponse(
                        success=False,
                        text="",
                        model=resolved,
                        duration_ms=(time.time() - start_time) * 1000.0,
                        error=f"Ollama returned HTTP {resp.status}",
                    )

        except urllib.error.URLError as e:
            return VisionResponse(
                success=False,
                text="",
                model=resolved,
                duration_ms=(time.time() - start_time) * 1000.0,
                error=f"Cannot reach Ollama at {self.base_url}: {e.reason}",
            )
        except Exception as e:
            return VisionResponse(
                success=False,
                text="",
                model=resolved,
                duration_ms=(time.time() - start_time) * 1000.0,
                error=f"Vision inference error: {str(e)}",
            )
