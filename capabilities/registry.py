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

    def is_operation_supported(self, capability_name: str, action: str) -> bool:
        """Check if an operation actually exists in the registry (with resilient routing)."""
        cap = self.get(capability_name)
        if cap and cap.has_operation(action):
            return True
        for other_cap in self._capabilities.values():
            if other_cap.has_operation(action):
                return True
        return False

    def get_structured_catalog(self) -> list[dict[str, Any]]:
        """Return structured capability descriptions for planner gating and documentation."""
        catalog = []
        for cap_name, cap in self._capabilities.items():
            for op in cap.get_operations():
                catalog.append({
                    "capability": cap_name,
                    "operation": op.name,
                    "description": op.description,
                    "parameters": op.parameters,
                    "platform": getattr(op, "platform", getattr(cap, "platform", "macos")),
                    "risk_level": op.default_risk.value,
                    "verification_support": getattr(op, "verification_support", "deterministic"),
                })
        return catalog


    def execute(self, capability_name: str, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Execute an action on a named capability with resilient routing."""
        cap = self.get(capability_name)
        if cap and cap.has_operation(action):
            return cap.execute(action, args)

        # Resilient routing: if action is declared in another registered capability, auto-route
        for other_name, other_cap in self._capabilities.items():
            if other_cap.has_operation(action):
                return other_cap.execute(action, args)

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
