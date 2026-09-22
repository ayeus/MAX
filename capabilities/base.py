"""Base interfaces and models for MAX capabilities."""

from abc import ABC, abstractmethod
from enum import Enum
from pydantic import BaseModel, Field
from typing import Any, Callable
from security.risk import RiskLevel


class ExecutionResult(BaseModel):
    """The result of executing a capability operation, containing real evidence."""
    success: bool
    capability: str
    action: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0


class Operation(BaseModel):
    """An individual operation provided by a capability."""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    default_risk: RiskLevel = RiskLevel.LOW
    handler: Callable[..., ExecutionResult] | None = None

    class Config:
        arbitrary_types_allowed = True


class Capability(ABC):
    """Abstract base class for a system capability."""

    name: str
    description: str

    @abstractmethod
    def get_operations(self) -> list[Operation]:
        """Return list of operations supported by this capability."""
        pass

    def get_schema(self) -> dict[str, Any]:
        """Return JSON-serializable schema for the planner LLM."""
        return {
            "capability": self.name,
            "description": self.description,
            "operations": [
                {
                    "name": op.name,
                    "description": op.description,
                    "parameters": op.parameters,
                    "default_risk": op.default_risk.value,
                }
                for op in self.get_operations()
            ],
        }

    def execute(self, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Execute a specific action with provided arguments."""
        for op in self.get_operations():
            if op.name == action:
                if op.handler:
                    try:
                        return op.handler(**args)
                    except TypeError as te:
                        return ExecutionResult(
                            success=False,
                            capability=self.name,
                            action=action,
                            error=f"Invalid arguments for operation '{action}': {te}",
                        )
                return self.handle_action(action, args)
        try:
            return self.handle_action(action, args)
        except NotImplementedError:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action=action,
                error=f"Operation '{action}' not found in capability '{self.name}'.",
            )

    def handle_action(self, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Fallback action handler if no operation handler was explicitly registered."""
        raise NotImplementedError(f"Action '{action}' is not implemented in '{self.name}'.")
