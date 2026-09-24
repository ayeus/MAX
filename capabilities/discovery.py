"""Capability Discovery interfaces and result models for MAX Dynamic Capability Platform.

Separates discovery contracts from execution contracts, strictly distinguishing:
- Empty discovery (no capabilities found)
- Discovery failure (errors during discovery)
- Permission-blocked discovery (discovery prevented by macOS TCC permissions)
- Unavailable capabilities
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict

from .models import CapabilityDescriptor, CapabilityProvenance


class DiscoveryError(BaseModel):
    """Structured error encountered during capability discovery."""

    provider_id: str
    error_code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class PermissionBlockedDiscovery(BaseModel):
    """Information on a discovery probe that could not proceed due to missing permissions."""

    provider_id: str
    permission_name: str
    impact: str
    system_settings_path: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class DiscoveryResult(BaseModel):
    """Structured result of a capability discovery probe.

    Enforces that empty results and failed discovery are distinct states.
    """

    discovered_capabilities: list[CapabilityDescriptor] = Field(default_factory=list)
    unavailable_capabilities: list[CapabilityDescriptor] = Field(default_factory=list)
    errors: list[DiscoveryError] = Field(default_factory=list)
    permission_blocked: list[PermissionBlockedDiscovery] = Field(default_factory=list)
    provenance: Optional[CapabilityProvenance] = None
    duration_ms: float = 0.0

    model_config = ConfigDict(extra="ignore")

    @property
    def is_empty(self) -> bool:
        """True only if discovery succeeded with zero capabilities and zero errors."""
        return (
            len(self.discovered_capabilities) == 0
            and len(self.unavailable_capabilities) == 0
            and not self.has_errors
            and not self.is_blocked_by_permission
        )

    @property
    def has_errors(self) -> bool:
        """True if any discovery errors occurred."""
        return len(self.errors) > 0

    @property
    def is_blocked_by_permission(self) -> bool:
        """True if discovery was blocked by missing system permissions."""
        return len(self.permission_blocked) > 0


class CapabilityDiscoveryProvider(ABC):
    """Interface for providers capable of discovering capabilities."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier of this discovery provider."""
        pass

    @abstractmethod
    def discover(self) -> DiscoveryResult:
        """Perform discovery and return structured discovery result."""
        pass
