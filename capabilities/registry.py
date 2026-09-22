"""Capability Registry for MAX agent."""

from .base import Capability, ExecutionResult
from typing import Any


class CapabilityRegistry:
    """Central registry of all loaded computer capabilities."""

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a new capability."""
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        """Retrieve a capability by name."""
        return self._capabilities.get(name)

    def list_capabilities(self) -> list[str]:
        """List registered capability names."""
        return list(self._capabilities.keys())

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Return schema definitions for all registered capabilities."""
        return [cap.get_schema() for cap in self._capabilities.values()]

    def execute(self, capability_name: str, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Execute an action on a named capability."""
        cap = self.get(capability_name)
        if not cap:
            return ExecutionResult(
                success=False,
                capability=capability_name,
                action=action,
                error=f"Capability '{capability_name}' is not registered.",
            )
        return cap.execute(action, args)


# Global registry instance
registry = CapabilityRegistry()
