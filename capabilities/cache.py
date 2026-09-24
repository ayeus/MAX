"""Capability Cache contract and thread-safe in-memory cache for MAX Dynamic Capability Platform.

Provides performance acceleration for discovered capabilities without becoming an authoritative
source of truth. Supports targeted invalidation when applications, permissions, or sources change.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
import threading
from typing import Optional

from .models import CapabilityDescriptor


class CapabilityCache(ABC):
    """Abstract contract for capability descriptor caching."""

    @abstractmethod
    def get(self, capability_id: str, provider_id: Optional[str] = None) -> Optional[CapabilityDescriptor]:
        """Retrieve a cached capability descriptor."""
        pass

    @abstractmethod
    def put(self, descriptor: CapabilityDescriptor) -> None:
        """Store a capability descriptor in the cache."""
        pass

    @abstractmethod
    def invalidate_capability(self, capability_id: str) -> None:
        """Invalidate all cached entries for a specific capability ID."""
        pass

    @abstractmethod
    def invalidate_provider(self, provider_id: str) -> None:
        """Invalidate all cached entries for a specific provider."""
        pass

    @abstractmethod
    def invalidate_source(self, source_identifier: str) -> None:
        """Invalidate all cached entries originating from a specific source."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Evict all cached entries."""
        pass

    @abstractmethod
    def list_all(self) -> list[CapabilityDescriptor]:
        """Return all currently cached descriptors."""
        pass


class InMemoryCapabilityCache(CapabilityCache):
    """Thread-safe in-memory capability cache implementation."""

    def __init__(self):
        self._entries: dict[tuple[str, str], CapabilityDescriptor] = {}
        self._by_capability: dict[str, set[tuple[str, str]]] = {}
        self._by_provider: dict[str, set[tuple[str, str]]] = {}
        self._by_source: dict[str, set[tuple[str, str]]] = {}
        self._lock = threading.RLock()

    def get(self, capability_id: str, provider_id: Optional[str] = None) -> Optional[CapabilityDescriptor]:
        with self._lock:
            if provider_id is not None:
                return self._entries.get((capability_id, provider_id))
            # Return any matching provider entry if provider_id was not specified
            keys = self._by_capability.get(capability_id, set())
            for k in keys:
                return self._entries.get(k)
            return None

    def put(self, descriptor: CapabilityDescriptor) -> None:
        with self._lock:
            key = (descriptor.capability_id, descriptor.provider_id)
            self._entries[key] = descriptor

            self._by_capability.setdefault(descriptor.capability_id, set()).add(key)
            self._by_provider.setdefault(descriptor.provider_id, set()).add(key)

            if descriptor.provenance and descriptor.provenance.source_identifier:
                self._by_source.setdefault(descriptor.provenance.source_identifier, set()).add(key)

    def invalidate_capability(self, capability_id: str) -> None:
        with self._lock:
            keys = self._by_capability.pop(capability_id, set())
            for k in keys:
                self._remove_key(k)

    def invalidate_provider(self, provider_id: str) -> None:
        with self._lock:
            keys = self._by_provider.pop(provider_id, set())
            for k in keys:
                self._remove_key(k)

    def invalidate_source(self, source_identifier: str) -> None:
        with self._lock:
            keys = self._by_source.pop(source_identifier, set())
            for k in keys:
                self._remove_key(k)

    def _remove_key(self, key: tuple[str, str]) -> None:
        desc = self._entries.pop(key, None)
        if desc:
            cap_keys = self._by_capability.get(desc.capability_id)
            if cap_keys:
                cap_keys.discard(key)
                if not cap_keys:
                    self._by_capability.pop(desc.capability_id, None)

            prov_keys = self._by_provider.get(desc.provider_id)
            if prov_keys:
                prov_keys.discard(key)
                if not prov_keys:
                    self._by_provider.pop(desc.provider_id, None)

            if desc.provenance and desc.provenance.source_identifier:
                src_keys = self._by_source.get(desc.provenance.source_identifier)
                if src_keys:
                    src_keys.discard(key)
                    if not src_keys:
                        self._by_source.pop(desc.provenance.source_identifier, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._by_capability.clear()
            self._by_provider.clear()
            self._by_source.clear()

    def list_all(self) -> list[CapabilityDescriptor]:
        with self._lock:
            return list(self._entries.values())
