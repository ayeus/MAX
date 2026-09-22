"""Ollama provider implementation for MAX."""

import json
import urllib.request
import urllib.error
from app.config import settings
from .base import LLMProvider, LLMMessage, LLMResponse


class OllamaProvider(LLMProvider):
    """Local Ollama client interacting directly with the Ollama REST API."""

    def __init__(
        self,
        base_url: str = settings.ollama_base_url,
        model_name: str = settings.reasoning_model,
        timeout: float = settings.llm_timeout_seconds,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    def is_available(self) -> bool:
        """Verify Ollama instance is alive and reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Fetch list of models available in the local Ollama instance."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=4) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def warmup(self) -> bool:
        """Pre-warm and load the model into memory with keep_alive=-1 to eliminate cold-start latency."""
        try:
            payload = {
                "model": self.model_name,
                "keep_alive": -1,
            }
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_format: bool = False,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Generate response via Ollama /api/generate."""
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": temperature,
            },
        }
        if system:
            payload["system"] = system
        if json_format:
            payload["format"] = "json"

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                duration_ms = res_json.get("total_duration", 0) / 1_000_000.0
                return LLMResponse(
                    content=res_json.get("response", "").strip(),
                    model=self.model_name,
                    total_duration_ms=duration_ms,
                    prompt_eval_count=res_json.get("prompt_eval_count", 0),
                    eval_count=res_json.get("eval_count", 0),
                    raw_response=res_json,
                )
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}: {e}. Ensure Ollama is running (`ollama serve` or open Ollama.app)."
            ) from e

    def chat(
        self,
        messages: list[LLMMessage],
        json_format: bool = False,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Chat completion via Ollama /api/chat."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "keep_alive": -1,
            "options": {
                "temperature": temperature,
            },
        }
        if json_format:
            payload["format"] = "json"

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                duration_ms = res_json.get("total_duration", 0) / 1_000_000.0
                msg_content = res_json.get("message", {}).get("content", "").strip()
                return LLMResponse(
                    content=msg_content,
                    model=self.model_name,
                    total_duration_ms=duration_ms,
                    prompt_eval_count=res_json.get("prompt_eval_count", 0),
                    eval_count=res_json.get("eval_count", 0),
                    raw_response=res_json,
                )
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}: {e}."
            ) from e
