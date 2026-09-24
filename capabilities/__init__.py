"""Capabilities subsystem for MAX computer agent.

Provides both the canonical Dynamic Capability Platform interfaces and legacy
Phase 1 capability implementations.
"""

from .base import Capability, Operation, ExecutionResult
from .cache import CapabilityCache, InMemoryCapabilityCache
from .discovery import (
    CapabilityDiscoveryProvider,
    DiscoveryError,
    DiscoveryResult,
    PermissionBlockedDiscovery,
)
from .models import (
    AvailabilityInfo,
    AvailabilityStatus,
    CapabilityConstraint,
    CapabilityDescriptor,
    CapabilityProvenance,
    CapabilityRisk,
    CapabilityVersion,
    ConstraintType,
    OperationDescriptor,
    ProviderCharacteristics,
    ProviderHealth,
    RequiredPermission,
    VerificationContract,
    VerificationStrategy,
)
from .provider import (
    CapabilityExecutionProvider,
    CapabilityProvider,
    LegacyCapabilityAdapter,
)
from .registry import CapabilityRegistry, registry

from .accessibility import AccessibilityCapability
from .applications import ApplicationsCapability
from .browser import BrowserCapability
from .developer import DeveloperCapability
from .filesystem import FilesystemCapability
from .macos import MacOSSystemCapability
from .tasks import TaskCapability
from .terminal import TerminalCapability
from .vision import VisionCapability


def initialize_default_capabilities() -> CapabilityRegistry:
    """Initialize and register all core system capabilities."""
    if not registry.list_capabilities():
        registry.register(TerminalCapability())
        registry.register(FilesystemCapability())
        registry.register(ApplicationsCapability())
        registry.register(MacOSSystemCapability())
        registry.register(DeveloperCapability())
        registry.register(AccessibilityCapability())
        registry.register(BrowserCapability())
        registry.register(VisionCapability())
        registry.register(TaskCapability())
    return registry


__all__ = [
    # Legacy interfaces
    "Capability",
    "Operation",
    "ExecutionResult",
    "CapabilityRegistry",
    "registry",
    "initialize_default_capabilities",
    # Dynamic models
    "AvailabilityStatus",
    "AvailabilityInfo",
    "RequiredPermission",
    "CapabilityRisk",
    "ConstraintType",
    "CapabilityConstraint",
    "VerificationStrategy",
    "VerificationContract",
    "CapabilityProvenance",
    "CapabilityVersion",
    "ProviderHealth",
    "ProviderCharacteristics",
    "OperationDescriptor",
    "CapabilityDescriptor",
    # Provider interfaces
    "CapabilityDiscoveryProvider",
    "CapabilityExecutionProvider",
    "CapabilityProvider",
    "LegacyCapabilityAdapter",
    # Cache interfaces
    "CapabilityCache",
    "InMemoryCapabilityCache",
    # Discovery interfaces
    "DiscoveryError",
    "PermissionBlockedDiscovery",
    "DiscoveryResult",
    # Legacy capabilities
    "TerminalCapability",
    "FilesystemCapability",
    "ApplicationsCapability",
    "MacOSSystemCapability",
    "DeveloperCapability",
    "AccessibilityCapability",
    "BrowserCapability",
    "VisionCapability",
    "TaskCapability",
]
