"""Capabilities subsystem for MAX computer agent."""

from .base import Capability, Operation, ExecutionResult
from .registry import CapabilityRegistry, registry
from .terminal import TerminalCapability
from .filesystem import FilesystemCapability
from .applications import ApplicationsCapability
from .macos import MacOSSystemCapability
from .developer import DeveloperCapability
from .accessibility import AccessibilityCapability
from .browser import BrowserCapability
from .vision import VisionCapability
from .tasks import TaskCapability


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
    "Capability",
    "Operation",
    "ExecutionResult",
    "CapabilityRegistry",
    "registry",
    "initialize_default_capabilities",
    "TerminalCapability",
    "FilesystemCapability",
    "ApplicationsCapability",
    "MacOSSystemCapability",
    "DeveloperCapability",
]
