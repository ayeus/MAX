"""Capability Provider interfaces and Legacy Adapter for MAX Dynamic Capability Platform.

Separates discovery contracts from execution contracts, allowing:
- Discovery-only providers (e.g. app scanning, metadata enumeration)
- Execution-only providers (e.g. specialized system runners)
- Combined providers
- Transparent one-way adaptation of Phase 1 legacy Capability classes
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from .base import Capability, ExecutionResult
from .discovery import CapabilityDiscoveryProvider, DiscoveryResult
from .models import (
    AvailabilityInfo,
    AvailabilityStatus,
    CapabilityDescriptor,
    CapabilityProvenance,
    CapabilityRisk,
    CapabilityVersion,
    OperationDescriptor,
    ProviderCharacteristics,
    ProviderHealth,
    RequiredPermission,
    VerificationContract,
    VerificationStrategy,
)


class CapabilityExecutionProvider(ABC):
    """Interface for providers capable of executing capability operations."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier of this execution provider."""
        pass

    @property
    def provider_version(self) -> str:
        """Implementation version of this provider."""
        return "1.0.0"

    @abstractmethod
    def execute(self, capability_id: str, operation_id: str, args: dict[str, Any]) -> ExecutionResult:
        """Execute a specific operation on a capability with provided arguments."""
        pass

    def check_availability(self) -> AvailabilityStatus:
        """Probe provider availability."""
        return AvailabilityStatus.AVAILABLE

    def check_health(self) -> ProviderHealth:
        """Probe provider operational health and readiness."""
        return ProviderHealth(healthy=True)

    def get_characteristics(self) -> ProviderCharacteristics:
        """Return provider performance, verification quality, and reliability metadata."""
        return ProviderCharacteristics(
            provider_type="NATIVE",
            health=self.check_health(),
        )

    def get_required_permissions(self) -> list[RequiredPermission]:
        """Return permissions required by this execution provider."""
        return []

    def get_provenance(self) -> Optional[CapabilityProvenance]:
        """Return provenance describing this provider's origin and environment."""
        return CapabilityProvenance(
            provider_id=self.provider_id,
            discovery_mechanism="native",
        )


class CapabilityProvider(CapabilityDiscoveryProvider, CapabilityExecutionProvider):
    """Combined interface for providers that perform both discovery and execution."""
    pass


class LegacyCapabilityAdapter(CapabilityExecutionProvider):
    """One-way adapter transforming legacy Phase 1 Capability objects into Execution Providers."""

    def __init__(self, capability: Capability, provider_id: Optional[str] = None):
        self.legacy_capability = capability
        self._provider_id = provider_id or f"legacy_{capability.name}"

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def to_descriptor(self) -> CapabilityDescriptor:
        """Convert the wrapped legacy Capability into a canonical CapabilityDescriptor."""
        cap = self.legacy_capability
        ops: dict[str, OperationDescriptor] = {}

        for op in cap.get_operations():
            # Map legacy verification_support string to VerificationContract
            v_support = getattr(op, "verification_support", "deterministic")
            if v_support == "deterministic":
                v_strategy = VerificationStrategy.DIRECT_OBSERVATION
            elif v_support == "process":
                v_strategy = VerificationStrategy.PROCESS_OBSERVATION
            elif v_support == "filesystem":
                v_strategy = VerificationStrategy.FILESYSTEM_OBSERVATION
            elif v_support == "accessibility":
                v_strategy = VerificationStrategy.ACCESSIBILITY_OBSERVATION
            elif v_support == "browser":
                v_strategy = VerificationStrategy.BROWSER_OBSERVATION
            elif v_support == "terminal":
                v_strategy = VerificationStrategy.TERMINAL_OBSERVATION
            elif v_support == "model_assisted":
                v_strategy = VerificationStrategy.MODEL_ASSISTED
            else:
                v_strategy = VerificationStrategy.UNKNOWN

            v_contract = VerificationContract(
                strategy=v_strategy,
                is_verifiable=True,
                independent_observer_required=True,
                observer_source=getattr(op, "platform", "macos"),
                description=f"Legacy verification for {cap.name}.{op.name}",
            )

            ops[op.name] = OperationDescriptor(
                operation_id=op.name,
                capability_id=cap.name,
                name=op.name.replace("_", " ").title(),
                description=op.description,
                input_schema=op.parameters,
                output_schema={},
                availability=AvailabilityInfo(status=AvailabilityStatus.AVAILABLE),
                permissions=[],
                constraints=[],
                risk=CapabilityRisk(level=op.default_risk),
                verification=v_contract,
                metadata={"platform": getattr(op, "platform", "macos")},
            )

        return CapabilityDescriptor(
            capability_id=cap.name,
            name=cap.name.replace("_", " ").title(),
            description=cap.description,
            domain="system",
            operations=ops,
            provider_id=self.provider_id,
            version=CapabilityVersion(version="1.0.0", provider_version="1.0.0"),
            provenance=CapabilityProvenance(
                provider_id=self.provider_id,
                discovery_mechanism="static",
                source_identifier="legacy_capability",
            ),
            metadata={"platform": getattr(cap, "platform", "macos"), "is_legacy": True},
        )

    def execute(self, capability_id: str, operation_id: str, args: dict[str, Any]) -> ExecutionResult:
        """Delegate execution to wrapped legacy capability."""
        return self.legacy_capability.execute(operation_id, args)
