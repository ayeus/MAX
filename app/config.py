"""Configuration system for MAX agent.

All settings can be overridden via environment variables prefixed with MAX_.
Default paths are derived dynamically from the user's home directory.
"""

from pathlib import Path
from pydantic import BaseModel, Field
import os


class Settings(BaseModel):
    """Core settings for MAX agent."""

    # LLM Settings
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("MAX_OLLAMA_URL", "http://localhost:11434")
    )
    reasoning_model: str = Field(
        default_factory=lambda: os.getenv("MAX_REASONING_MODEL", "qwen2.5-7b-instruct:latest")
    )
    vision_model: str = Field(
        default_factory=lambda: os.getenv("MAX_VISION_MODEL", "qwen3-vl:8b")
    )
    llm_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MAX_LLM_TIMEOUT", "60.0"))
    )

    # Agent Loop Settings
    max_steps_per_task: int = Field(
        default_factory=lambda: int(os.getenv("MAX_MAX_STEPS", "10"))
    )
    command_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("MAX_COMMAND_TIMEOUT", "45"))
    )
    debug_mode: bool = Field(
        default_factory=lambda: os.getenv("MAX_DEBUG", "false").lower() in ("true", "1", "yes")
    )

    # Security Settings
    require_confirmation_for_high_risk: bool = Field(
        default_factory=lambda: os.getenv("MAX_CONFIRM_HIGH_RISK", "true").lower() in ("true", "1", "yes")
    )
    allow_network_tools: bool = Field(
        default_factory=lambda: os.getenv("MAX_ALLOW_NETWORK", "true").lower() in ("true", "1", "yes")
    )

    # Storage Paths (all dynamic, derived from user home)
    base_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("MAX_DATA_DIR", str(Path.home() / ".max")))
    )

    @property
    def log_dir(self) -> Path:
        return self.base_dir / "logs"

    @property
    def audit_log_path(self) -> Path:
        return self.base_dir / "audit.jsonl"

    @property
    def memory_db_path(self) -> Path:
        return self.base_dir / "memory.db"

    @property
    def workflows_dir(self) -> Path:
        return self.base_dir / "workflows"

    def ensure_directories(self) -> None:
        """Create necessary data and log directories if they don't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.workflows_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
settings.ensure_directories()
