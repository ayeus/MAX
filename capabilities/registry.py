"""Unified Capability Registry for MAX Dynamic Capability Platform.

Provides a provider-independent capability foundation supporting:
- Canonical CapabilityDescriptor and OperationDescriptor models
- Decoupled Discovery and Execution provider interfaces
- Multiple execution providers for a single capability without overwriting
- Explicit availability states and capability caching with targeted invalidation
- Complete one-way legacy adapter compatibility for Phase 1 callers
"""

from __future__ import annotations
import logging
from typing import Any, Optional

from .base import Capability, ExecutionResult
from .cache import CapabilityCache, InMemoryCapabilityCache
from .discovery import CapabilityDiscoveryProvider
from .models import (
    AvailabilityStatus,
    CapabilityDescriptor,
    OperationDescriptor,
)
from .provider import CapabilityExecutionProvider, LegacyCapabilityAdapter

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Central dynamic registry of computer capabilities and execution providers."""

    def __init__(self, cache: Optional[CapabilityCache] = None):
        # Canonical mappings: capability_id -> dict[provider_id, CapabilityDescriptor]
        self._capabilities: dict[str, dict[str, CapabilityDescriptor]] = {}
        # Operation mapping: (capability_id, operation_id) -> dict[provider_id, OperationDescriptor]
        self._operations: dict[tuple[str, str], dict[str, OperationDescriptor]] = {}

        # Providers
        self._execution_providers: dict[str, CapabilityExecutionProvider] = {}
        self._discovery_providers: dict[str, CapabilityDiscoveryProvider] = {}

        # Legacy compatibility store
        self._legacy_capabilities: dict[str, Capability] = {}

        # Cache
        self._cache: CapabilityCache = cache or InMemoryCapabilityCache()

    # -------------------------------------------------------------------------
    # Provider Registration
    # -------------------------------------------------------------------------

    def register_execution_provider(self, provider: CapabilityExecutionProvider) -> None:
        """Register an execution provider."""
        self._execution_providers[provider.provider_id] = provider

    def unregister_execution_provider(self, provider_id: str) -> None:
        """Unregister an execution provider and purge its descriptors."""
        self._execution_providers.pop(provider_id, None)
        # Purge capabilities provided by this provider
        for cap_id in list(self._capabilities.keys()):
            self.unregister_capability(cap_id, provider_id=provider_id)
        self._cache.invalidate_provider(provider_id)

    def register_discovery_provider(self, provider: CapabilityDiscoveryProvider) -> None:
        """Register a discovery provider."""
        self._discovery_providers[provider.provider_id] = provider

    def unregister_discovery_provider(self, provider_id: str) -> None:
        """Unregister a discovery provider."""
        self._discovery_providers.pop(provider_id, None)

    # -------------------------------------------------------------------------
    # Capability & Operation Registration (Multi-Provider Aware)
    # -------------------------------------------------------------------------

    def register_capability(
        self,
        descriptor: CapabilityDescriptor,
        provider: Optional[CapabilityExecutionProvider] = None,
    ) -> None:
        """Register a canonical capability descriptor.

        Multi-provider invariant: Registering a descriptor from provider B for
        an existing capability_id does NOT overwrite provider A's descriptor.
        """
        if provider is not None:
            self.register_execution_provider(provider)

        cap_id = descriptor.capability_id
        prov_id = descriptor.provider_id

        if cap_id not in self._capabilities:
            self._capabilities[cap_id] = {}
        self._capabilities[cap_id][prov_id] = descriptor

        # Register individual operations
        for op_id, op in descriptor.operations.items():
            key = (cap_id, op_id)
            if key not in self._operations:
                self._operations[key] = {}
            self._operations[key][prov_id] = op

        # Cache descriptor
        self._cache.put(descriptor)

    def unregister_capability(self, capability_id: str, provider_id: Optional[str] = None) -> None:
        """Unregister a capability. If provider_id is None, removes all providers."""
        if provider_id is not None:
            prov_map = self._capabilities.get(capability_id)
            if prov_map:
                prov_map.pop(provider_id, None)
                if not prov_map:
                    self._capabilities.pop(capability_id, None)

            # Purge matching operations
            for (c_id, op_id), ops in list(self._operations.items()):
                if c_id == capability_id:
                    ops.pop(provider_id, None)
                    if not ops:
                        self._operations.pop((c_id, op_id), None)
        else:
            self._capabilities.pop(capability_id, None)
            for (c_id, op_id) in list(self._operations.keys()):
                if c_id == capability_id:
                    self._operations.pop((c_id, op_id), None)

        self._cache.invalidate_capability(capability_id)

    # -------------------------------------------------------------------------
    # Query & Retrieval
    # -------------------------------------------------------------------------

    def get_capability(
        self, capability_id: str, provider_id: Optional[str] = None
    ) -> Optional[CapabilityDescriptor]:
        """Retrieve a capability descriptor.

        If provider_id is omitted, returns the first available provider's descriptor.
        """
        prov_map = self._capabilities.get(capability_id)
        if not prov_map:
            return self._cache.get(capability_id, provider_id)

        if provider_id is not None:
            return prov_map.get(provider_id)

        # Return first available provider descriptor if present
        for desc in prov_map.values():
            return desc
        return None

    def get_operation(
        self, capability_id: str, operation_id: str, provider_id: Optional[str] = None
    ) -> Optional[OperationDescriptor]:
        """Retrieve an operation descriptor."""
        key = (capability_id, operation_id)
        ops_map = self._operations.get(key)
        if not ops_map:
            return None

        if provider_id is not None:
            return ops_map.get(provider_id)

        for op in ops_map.values():
            return op
        return None

    def providers_for(
        self, capability_id: str, operation_id: Optional[str] = None
    ) -> list[CapabilityExecutionProvider]:
        """Return all execution providers that supply this capability (or operation)."""
        providers: list[CapabilityExecutionProvider] = []

        if operation_id is not None:
            ops_map = self._operations.get((capability_id, operation_id), {})
            for prov_id in ops_map.keys():
                prov = self._execution_providers.get(prov_id)
                if prov and prov not in providers:
                    providers.append(prov)
        else:
            prov_map = self._capabilities.get(capability_id, {})
            for prov_id in prov_map.keys():
                prov = self._execution_providers.get(prov_id)
                if prov and prov not in providers:
                    providers.append(prov)

        return providers

    def find_capabilities(
        self,
        domain: Optional[str] = None,
        provider_id: Optional[str] = None,
        availability: Optional[AvailabilityStatus] = None,
        query: Optional[str] = None,
    ) -> list[CapabilityDescriptor]:
        """Find descriptors matching specific query filters."""
        results: list[CapabilityDescriptor] = []
        q_lower = query.lower() if query else None

        for prov_map in self._capabilities.values():
            for desc in prov_map.values():
                if domain is not None and desc.domain != domain:
                    continue
                if provider_id is not None and desc.provider_id != provider_id:
                    continue
                if q_lower:
                    match_name = q_lower in desc.name.lower()
                    match_desc = q_lower in desc.description.lower()
                    match_id = q_lower in desc.capability_id.lower()
                    if not (match_name or match_desc or match_id):
                        continue
                if availability is not None:
                    # Filter operations or capability availability
                    has_matching_op = any(
                        op.availability.status == availability for op in desc.operations.values()
                    )
                    if not has_matching_op:
                        continue
                results.append(desc)

        return results

    def update_availability(
        self,
        capability_id: str,
        provider_id: str,
        status: AvailabilityStatus,
        operation_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Update availability status of a registered capability or operation."""
        desc = self.get_capability(capability_id, provider_id)
        if desc:
            if operation_id is not None:
                op = desc.get_operation(operation_id)
                if op:
                    op.availability.status = status
                    op.availability.reason = reason
            else:
                for op in desc.operations.values():
                    op.availability.status = status
                    op.availability.reason = reason
            self._cache.put(desc)

    def invalidate(
        self,
        capability_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> None:
        """Invalidate cached capability data."""
        if capability_id:
            self._cache.invalidate_capability(capability_id)
        if provider_id:
            self._cache.invalidate_provider(provider_id)
        if source:
            self._cache.invalidate_source(source)
        if not (capability_id or provider_id or source):
            self._cache.clear()

    # -------------------------------------------------------------------------
    # Legacy Compatibility Layer (Phase 1 Callers)
    # -------------------------------------------------------------------------

    def register(
        self,
        capability: Capability | CapabilityDescriptor,
        provider: Optional[CapabilityExecutionProvider] = None,
    ) -> None:
        """Register a capability or legacy Capability instance."""
        if isinstance(capability, Capability):
            self._legacy_capabilities[capability.name] = capability
            adapter = LegacyCapabilityAdapter(capability)
            self.register_capability(adapter.to_descriptor(), provider=adapter)
        elif isinstance(capability, CapabilityDescriptor):
            self.register_capability(capability, provider=provider)
        else:
            raise TypeError(f"Expected Capability or CapabilityDescriptor, got {type(capability)}")

    def get(self, name: str) -> Capability | None:
        """Retrieve legacy Capability instance for backward compatibility."""
        return self._legacy_capabilities.get(name)

    def get_legacy_capability(self, name: str) -> Capability | None:
        """Explicit backward-compatibility accessor for legacy Capability objects."""
        return self.get(name)

    def list_capabilities(self) -> list[str]:
        """List registered capability names (both legacy names and canonical IDs)."""
        names = set(self._legacy_capabilities.keys())
        names.update(self._capabilities.keys())
        return list(names)

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Return JSON schemas for planner LLM."""
        schemas = [cap.get_schema() for cap in self._legacy_capabilities.values()]
        # Also include non-legacy descriptors converted to schema format
        for cap_id, prov_map in self._capabilities.items():
            if cap_id not in self._legacy_capabilities:
                for desc in prov_map.values():
                    schemas.append({
                        "capability": desc.capability_id,
                        "description": desc.description,
                        "platform": desc.metadata.get("platform", "macos"),
                        "operations": [
                            {
                                "name": op.operation_id,
                                "description": op.description,
                                "parameters": op.input_schema,
                                "platform": op.metadata.get("platform", "macos"),
                                "default_risk": op.risk.level.value,
                                "verification_support": op.verification.strategy.value.lower(),
                            }
                            for op in desc.operations.values()
                        ],
                    })
                    break
        return schemas

    def is_operation_supported(self, capability_name: str, action: str) -> bool:
        """Check if an operation is registered and available (with resilient routing)."""
        # 1. Check legacy capability direct match
        legacy_cap = self.get(capability_name)
        if legacy_cap and legacy_cap.has_operation(action):
            return True

        # 2. Check canonical operation descriptor
        op_desc = self.get_operation(capability_name, action)
        if op_desc and op_desc.availability.status == AvailabilityStatus.AVAILABLE:
            return True

        # 3. Check resilient cross-capability routing across legacy capabilities
        for other_cap in self._legacy_capabilities.values():
            if other_cap.has_operation(action):
                return True

        # 4. Check resilient cross-capability routing across canonical descriptors
        for (c_id, op_id), ops_map in self._operations.items():
            if op_id == action:
                for op in ops_map.values():
                    if op.availability.status == AvailabilityStatus.AVAILABLE:
                        return True

        return False

    def get_structured_catalog(self) -> list[dict[str, Any]]:
        """Return structured catalog for planner gating and documentation."""
        catalog = []
        for cap_name, cap in self._legacy_capabilities.items():
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
        """Execute an action on a named capability with resilient routing and multi-provider support."""
        # 1. Try legacy capability direct match
        legacy_cap = self.get(capability_name)
        if legacy_cap and legacy_cap.has_operation(action):
            return legacy_cap.execute(action, args)

        # 2. Try execution providers registered for (capability_name, action)
        providers = self.providers_for(capability_name, action)
        for provider in providers:
            if provider.check_availability() == AvailabilityStatus.AVAILABLE:
                return provider.execute(capability_name, action, args)

        # 3. Resilient routing across legacy capabilities
        for other_name, other_cap in self._legacy_capabilities.items():
            if other_cap.has_operation(action):
                return other_cap.execute(action, args)

        # 4. Resilient routing across canonical operations
        for (c_id, op_id), ops_map in self._operations.items():
            if op_id == action:
                for prov_id, op in ops_map.items():
                    if op.availability.status == AvailabilityStatus.AVAILABLE:
                        prov = self._execution_providers.get(prov_id)
                        if prov and prov.check_availability() == AvailabilityStatus.AVAILABLE:
                            return prov.execute(c_id, op_id, args)

        # 5. Fallback error if completely unregistered
        return ExecutionResult(
            success=False,
            capability=capability_name,
            action=action,
            error=f"Capability or operation '{capability_name}.{action}' is not registered or available.",
        )


# Global registry singleton
registry = CapabilityRegistry()
