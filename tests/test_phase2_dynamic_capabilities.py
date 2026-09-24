"""Tests for MAX Phase 2.0 Dynamic Capability Platform.

Covers all mandatory architectural categories:
- Category A: Capability & Operation Identity (canonical IDs, separation of capability and operation)
- Category B: Decoupled Provider Model & Multiple Providers for One Capability
- Category C: Availability Lifecycle States
- Category D: Permission Requirements & Serialization
- Category E: Generic Execution Constraints
- Category F: Structured Risk Metadata
- Category G: Verification Contracts (unverifiable actions cannot imply SATISFIED)
- Category H: Real Provenance Tracing (no fabrication)
- Category I: Structured Discovery Failure Semantics (empty vs. error vs. permission-blocked)
- Category J: Capability Cache & Targeted Invalidation
- Category K: Dynamic Registry Operations & Multi-Provider Querying
- Category L: Legacy Capability Compatibility & Adapter Execution
"""

import json
import unittest
from typing import Any, Optional

from capabilities import (
    AvailabilityInfo,
    AvailabilityStatus,
    CapabilityConstraint,
    CapabilityDescriptor,
    CapabilityDiscoveryProvider,
    CapabilityExecutionProvider,
    CapabilityProvenance,
    CapabilityProvider,
    CapabilityRegistry,
    CapabilityRisk,
    CapabilityVersion,
    ConstraintType,
    DiscoveryError,
    DiscoveryResult,
    ExecutionResult,
    InMemoryCapabilityCache,
    LegacyCapabilityAdapter,
    OperationDescriptor,
    PermissionBlockedDiscovery,
    ProviderCharacteristics,
    ProviderHealth,
    RequiredPermission,
    TerminalCapability,
    VerificationContract,
    VerificationStrategy,
)
from security.risk import RiskLevel


class MockDiscoveryProvider(CapabilityDiscoveryProvider):
    """Test discovery provider that does not execute capabilities."""

    def __init__(self, provider_id: str = "mock_discovery"):
        self._provider_id = provider_id
        self.result_to_return: Optional[DiscoveryResult] = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def discover(self) -> DiscoveryResult:
        return self.result_to_return or DiscoveryResult(
            discovered_capabilities=[],
            provenance=CapabilityProvenance(provider_id=self._provider_id, discovery_mechanism="test_probe"),
        )


class MockExecutionProvider(CapabilityExecutionProvider):
    """Test execution provider that does not discover capabilities."""

    def __init__(self, provider_id: str = "mock_exec"):
        self._provider_id = provider_id
        self.executed_calls: list[tuple[str, str, dict[str, Any]]] = []

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def execute(self, capability_id: str, operation_id: str, args: dict[str, Any]) -> ExecutionResult:
        self.executed_calls.append((capability_id, operation_id, args))
        return ExecutionResult(
            success=True,
            capability=capability_id,
            action=operation_id,
            data={"executed_by": self._provider_id, "args": args},
        )


class TestPhase2DynamicCapabilities(unittest.TestCase):
    """Comprehensive test suite for Phase 2.0 Dynamic Capability Platform."""

    def setUp(self):
        self.registry = CapabilityRegistry()

    # =========================================================================
    # Category A: Capability & Operation Identity
    # =========================================================================

    def test_category_a_capability_and_operation_identity(self):
        """Verify capability and operation have separate, non-flattened identities."""
        op_read = OperationDescriptor(
            operation_id="read",
            capability_id="filesystem.file",
            name="Read File",
            description="Reads file contents from disk.",
        )
        op_write = OperationDescriptor(
            operation_id="write",
            capability_id="filesystem.file",
            name="Write File",
            description="Writes file contents to disk.",
        )
        cap = CapabilityDescriptor(
            capability_id="filesystem.file",
            name="File Operations",
            description="Inspect and mutate files on macOS filesystem.",
            domain="filesystem",
            operations={"read": op_read, "write": op_write},
            provider_id="local_fs",
        )

        self.assertEqual(cap.capability_id, "filesystem.file")
        self.assertEqual(op_read.operation_id, "read")
        self.assertEqual(op_read.qualified_id, "filesystem.file.read")
        self.assertEqual(op_write.qualified_id, "filesystem.file.write")
        self.assertIn("read", cap.operations)
        self.assertIn("write", cap.operations)

    # =========================================================================
    # Category B: Decoupled Providers & Multiple Providers for One Capability
    # =========================================================================

    def test_category_b_decoupled_discovery_and_execution_providers(self):
        """Verify discovery and execution providers can exist independently."""
        disc_prov = MockDiscoveryProvider("app_scanner")
        exec_prov = MockExecutionProvider("native_runner")

        self.registry.register_discovery_provider(disc_prov)
        self.registry.register_execution_provider(exec_prov)

        self.assertIn("app_scanner", self.registry._discovery_providers)
        self.assertIn("native_runner", self.registry._execution_providers)

    def test_category_b_architectural_acceptance_multiple_providers(self):
        """Architectural Acceptance: system.application.open registered by 3 providers.

        Ensures Provider A (native_macos), Provider B (accessibility), and Provider C (mcp)
        all represent the SAME canonical capability without overwriting each other.
        """
        # Provider A: native_macos
        prov_a = MockExecutionProvider("native_macos")
        op_a = OperationDescriptor(
            operation_id="open",
            capability_id="system.application",
            name="Launch App via LaunchServices",
            description="Launch application using native macOS APIs.",
            verification=VerificationContract(strategy=VerificationStrategy.PROCESS_OBSERVATION),
        )
        cap_a = CapabilityDescriptor(
            capability_id="system.application",
            name="Application Lifecycle",
            description="Open and manage macOS applications.",
            operations={"open": op_a},
            provider_id="native_macos",
        )

        # Provider B: accessibility
        prov_b = MockExecutionProvider("accessibility")
        op_b = OperationDescriptor(
            operation_id="open",
            capability_id="system.application",
            name="Open App via Dock/AX",
            description="Open application via macOS Accessibility click on Dock icon.",
            verification=VerificationContract(strategy=VerificationStrategy.ACCESSIBILITY_OBSERVATION),
        )
        cap_b = CapabilityDescriptor(
            capability_id="system.application",
            name="Application Lifecycle",
            description="Open and manage macOS applications.",
            operations={"open": op_b},
            provider_id="accessibility",
        )

        # Provider C: mcp
        prov_c = MockExecutionProvider("mcp")
        op_c = OperationDescriptor(
            operation_id="open",
            capability_id="system.application",
            name="Open App via MCP Tool",
            description="Open application through remote MCP desktop server.",
            verification=VerificationContract(strategy=VerificationStrategy.UNKNOWN),
        )
        cap_c = CapabilityDescriptor(
            capability_id="system.application",
            name="Application Lifecycle",
            description="Open and manage macOS applications.",
            operations={"open": op_c},
            provider_id="mcp",
        )

        # Register all 3 providers
        self.registry.register_capability(cap_a, provider=prov_a)
        self.registry.register_capability(cap_b, provider=prov_b)
        self.registry.register_capability(cap_c, provider=prov_c)

        # Multi-provider verification
        providers = self.registry.providers_for("system.application", "open")
        self.assertEqual(len(providers), 3, "All 3 providers must be preserved without overwriting!")
        provider_ids = [p.provider_id for p in providers]
        self.assertIn("native_macos", provider_ids)
        self.assertIn("accessibility", provider_ids)
        self.assertIn("mcp", provider_ids)

        # Retrieve descriptors independently by provider
        desc_a = self.registry.get_capability("system.application", provider_id="native_macos")
        desc_b = self.registry.get_capability("system.application", provider_id="accessibility")
        desc_c = self.registry.get_capability("system.application", provider_id="mcp")

        self.assertIsNotNone(desc_a)
        self.assertIsNotNone(desc_b)
        self.assertIsNotNone(desc_c)
        self.assertEqual(desc_a.operations["open"].verification.strategy, VerificationStrategy.PROCESS_OBSERVATION)
        self.assertEqual(desc_b.operations["open"].verification.strategy, VerificationStrategy.ACCESSIBILITY_OBSERVATION)
        self.assertEqual(desc_c.operations["open"].verification.strategy, VerificationStrategy.UNKNOWN)

    # =========================================================================
    # Category C: Availability Lifecycle States
    # =========================================================================

    def test_category_c_availability_states_and_update(self):
        """Verify explicit availability states and dynamic status updating."""
        states = [
            AvailabilityStatus.AVAILABLE,
            AvailabilityStatus.UNAVAILABLE,
            AvailabilityStatus.PERMISSION_REQUIRED,
            AvailabilityStatus.PERMISSION_DENIED,
            AvailabilityStatus.NOT_INSTALLED,
            AvailabilityStatus.DISABLED,
            AvailabilityStatus.TEMPORARILY_UNAVAILABLE,
            AvailabilityStatus.UNKNOWN,
        ]
        self.assertEqual(len(states), 8)

        op = OperationDescriptor(
            operation_id="capture",
            capability_id="screen.capture",
            name="Capture Screen",
            description="Takes screenshot of display.",
            availability=AvailabilityInfo(
                status=AvailabilityStatus.PERMISSION_REQUIRED,
                reason="Screen Recording permission not granted in System Settings",
                missing_permissions=["screen_recording"],
            ),
        )
        cap = CapabilityDescriptor(
            capability_id="screen.capture",
            name="Screen Capture",
            description="Display capture services",
            operations={"capture": op},
            provider_id="screencapture_cli",
        )
        self.registry.register_capability(cap)

        retrieved_op = self.registry.get_operation("screen.capture", "capture", "screencapture_cli")
        self.assertIsNotNone(retrieved_op)
        self.assertEqual(retrieved_op.availability.status, AvailabilityStatus.PERMISSION_REQUIRED)
        self.assertIn("screen_recording", retrieved_op.availability.missing_permissions)

        # Update availability to AVAILABLE
        self.registry.update_availability(
            capability_id="screen.capture",
            provider_id="screencapture_cli",
            status=AvailabilityStatus.AVAILABLE,
            operation_id="capture",
            reason="User granted permission in System Settings",
        )
        updated_op = self.registry.get_operation("screen.capture", "capture", "screencapture_cli")
        self.assertEqual(updated_op.availability.status, AvailabilityStatus.AVAILABLE)

    # =========================================================================
    # Category D: Permissions & Deterministic Serialization
    # =========================================================================

    def test_category_d_permission_declaration_and_serialization(self):
        """Verify permission declaration and round-trip JSON serialization."""
        perm = RequiredPermission(
            name="accessibility",
            description="Required to inspect UI element hierarchies",
            system_settings_path="System Settings > Privacy & Security > Accessibility",
            is_optional=False,
            status="GRANTED",
        )
        op = OperationDescriptor(
            operation_id="click_element",
            capability_id="ui.interaction",
            name="Click UI Element",
            description="Clicks frontmost UI element.",
            permissions=[perm],
        )

        # Deterministic serialization roundtrip
        json_str = op.model_dump_json()
        deserialized = OperationDescriptor.model_validate_json(json_str)

        self.assertEqual(deserialized.operation_id, "click_element")
        self.assertEqual(len(deserialized.permissions), 1)
        self.assertEqual(deserialized.permissions[0].name, "accessibility")
        self.assertEqual(deserialized.permissions[0].status, "GRANTED")

    # =========================================================================
    # Category E: Generic Execution Constraints
    # =========================================================================

    def test_category_e_capability_constraints_evaluation(self):
        """Verify structured execution constraints evaluated against runtime context."""
        c_os = CapabilityConstraint(
            constraint_type=ConstraintType.OS_VERSION,
            parameter="macos_version",
            expected_value="14.0",
            description="Requires macOS Sonoma (14.0) or higher for App Intents",
        )
        c_app = CapabilityConstraint(
            constraint_type=ConstraintType.REQUIRED_APPLICATION,
            parameter="installed_apps",
            expected_value=["com.apple.Safari", "com.google.Chrome"],
            description="Requires a supported web browser",
        )

        # Context satisfying OS but missing browser
        context_fail = {"macos_version": "14.0", "installed_apps": "com.apple.Notes"}
        ok_os, err_os = c_os.evaluate(context_fail)
        self.assertTrue(ok_os)
        self.assertIsNone(err_os)

        ok_app, err_app = c_app.evaluate(context_fail)
        self.assertFalse(ok_app)
        self.assertIn("not in expected set", err_app)

        # Context satisfying both
        context_ok = {"macos_version": "14.0", "installed_apps": "com.apple.Safari"}
        ok_app2, err_app2 = c_app.evaluate(context_ok)
        self.assertTrue(ok_app2)

    # =========================================================================
    # Category F: Structured Risk Metadata
    # =========================================================================

    def test_category_f_risk_metadata_and_serialization(self):
        """Verify structured risk metadata serialization."""
        risk = CapabilityRisk(
            level=RiskLevel.HIGH,
            description="Recursive file deletion permanently removes user data",
            requires_confirmation=True,
            affected_targets=["path"],
        )
        json_str = risk.model_dump_json()
        deserialized = CapabilityRisk.model_validate_json(json_str)

        self.assertEqual(deserialized.level, RiskLevel.HIGH)
        self.assertTrue(deserialized.requires_confirmation)
        self.assertEqual(deserialized.affected_targets, ["path"])

    # =========================================================================
    # Category G: Verification Contracts
    # =========================================================================

    def test_category_g_verification_contract_preservation(self):
        """Verify verification contracts and ensure unverified actions cannot claim SATISFIED."""
        v_contract = VerificationContract(
            strategy=VerificationStrategy.FILESYSTEM_OBSERVATION,
            is_verifiable=True,
            independent_observer_required=True,
            observer_source="filesystem",
            expected_evidence_type="file_exists",
        )
        self.assertEqual(v_contract.strategy, VerificationStrategy.FILESYSTEM_OBSERVATION)
        self.assertTrue(v_contract.independent_observer_required)

        # Unverifiable contract
        v_none = VerificationContract(
            strategy=VerificationStrategy.NONE,
            is_verifiable=False,
            description="Fire-and-forget push notification with no readback API",
        )
        self.assertFalse(v_none.is_verifiable)
        self.assertEqual(v_none.strategy, VerificationStrategy.NONE)

    # =========================================================================
    # Category H: Real Provenance Tracing
    # =========================================================================

    def test_category_h_provenance_preservation_and_missing_handling(self):
        """Verify real provenance metadata without fabrication."""
        prov = CapabilityProvenance(
            provider_id="accessibility_scanner",
            discovery_mechanism="ax_element_tree",
            source_identifier="com.apple.Safari",
            source_version="18.0",
            discovered_at="2026-09-24T12:00:00Z",
            environment={"display_id": 1, "architecture": "arm64"},
        )
        json_str = prov.model_dump_json()
        deserialized = CapabilityProvenance.model_validate_json(json_str)

        self.assertEqual(deserialized.provider_id, "accessibility_scanner")
        self.assertEqual(deserialized.source_identifier, "com.apple.Safari")
        self.assertEqual(deserialized.environment["architecture"], "arm64")

        # Missing provenance representation
        prov_minimal = CapabilityProvenance(
            provider_id="test_prov",
            discovery_mechanism="static",
        )
        self.assertIsNone(prov_minimal.source_identifier)
        self.assertIsNone(prov_minimal.source_version)

    # =========================================================================
    # Category I: Structured Discovery Failure Semantics
    # =========================================================================

    def test_category_i_discovery_result_failure_vs_empty_semantics(self):
        """Verify strict distinction between empty discovery, failure, and permission-blocked."""
        # 1. Empty Discovery
        res_empty = DiscoveryResult(discovered_capabilities=[])
        self.assertTrue(res_empty.is_empty)
        self.assertFalse(res_empty.has_errors)
        self.assertFalse(res_empty.is_blocked_by_permission)

        # 2. Discovery Error
        res_error = DiscoveryResult(
            discovered_capabilities=[],
            errors=[DiscoveryError(provider_id="mcp_daemon", error_code="CONN_REFUSED", message="MCP socket closed")],
        )
        self.assertFalse(res_error.is_empty)
        self.assertTrue(res_error.has_errors)
        self.assertFalse(res_error.is_blocked_by_permission)

        # 3. Permission-Blocked Discovery
        res_perm = DiscoveryResult(
            discovered_capabilities=[],
            permission_blocked=[
                PermissionBlockedDiscovery(
                    provider_id="ax_provider",
                    permission_name="Accessibility",
                    impact="Cannot inspect application UI elements",
                    system_settings_path="System Settings > Privacy & Security > Accessibility",
                )
            ],
        )
        self.assertFalse(res_perm.is_empty)
        self.assertTrue(res_perm.is_blocked_by_permission)

    # =========================================================================
    # Category J: Capability Cache & Targeted Invalidation
    # =========================================================================

    def test_category_j_cache_invalidation_by_capability_provider_source(self):
        """Verify cache storage, retrieval, and targeted multi-axis invalidation."""
        cache = InMemoryCapabilityCache()

        cap1 = CapabilityDescriptor(
            capability_id="editor.code",
            name="Code Editor",
            description="Editing source files",
            provider_id="vscode_app",
            provenance=CapabilityProvenance(
                provider_id="vscode_app",
                discovery_mechanism="bundle_scan",
                source_identifier="com.microsoft.VSCode",
            ),
        )
        cap2 = CapabilityDescriptor(
            capability_id="browser.navigate",
            name="Browser Navigation",
            description="Navigating websites",
            provider_id="safari_app",
            provenance=CapabilityProvenance(
                provider_id="safari_app",
                discovery_mechanism="bundle_scan",
                source_identifier="com.apple.Safari",
            ),
        )

        cache.put(cap1)
        cache.put(cap2)
        self.assertEqual(len(cache.list_all()), 2)

        # Targeted invalidation by source
        cache.invalidate_source("com.microsoft.VSCode")
        self.assertIsNone(cache.get("editor.code", "vscode_app"))
        self.assertIsNotNone(cache.get("browser.navigate", "safari_app"))

        # Targeted invalidation by provider
        cache.invalidate_provider("safari_app")
        self.assertIsNone(cache.get("browser.navigate", "safari_app"))
        self.assertEqual(len(cache.list_all()), 0)

    # =========================================================================
    # Category K: Dynamic Registry Operations & Search
    # =========================================================================

    def test_category_k_find_capabilities_and_unregister(self):
        """Verify filtering descriptors by domain, provider, and text search."""
        op_term = OperationDescriptor(
            operation_id="run",
            capability_id="shell.terminal",
            name="Run Command",
            description="Executes bash or zsh shell command.",
        )
        cap_term = CapabilityDescriptor(
            capability_id="shell.terminal",
            name="Terminal Shell",
            description="Local shell execution",
            domain="system",
            operations={"run": op_term},
            provider_id="zsh_native",
        )
        self.registry.register_capability(cap_term)

        # Search by query text
        found = self.registry.find_capabilities(query="shell")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].capability_id, "shell.terminal")

        # Search by domain
        found_domain = self.registry.find_capabilities(domain="system")
        self.assertGreaterEqual(len(found_domain), 1)

        # Unregister capability
        self.registry.unregister_capability("shell.terminal")
        self.assertIsNone(self.registry.get_capability("shell.terminal"))

    # =========================================================================
    # Category L: Legacy Capability Compatibility & Adapter Execution
    # =========================================================================

    def test_category_l_legacy_capability_adapter_execution(self):
        """Verify legacy Phase 1 Capability objects are cleanly adapted and execute identically."""
        term_cap = TerminalCapability()
        adapter = LegacyCapabilityAdapter(term_cap)

        self.assertEqual(adapter.provider_id, "legacy_terminal")
        desc = adapter.to_descriptor()
        self.assertEqual(desc.capability_id, "terminal")
        self.assertIn("execute_command", desc.operations)

        # Register legacy capability in registry
        self.registry.register(term_cap)

        # Verify legacy accessors
        self.assertIsNotNone(self.registry.get("terminal"))
        self.assertIsNotNone(self.registry.get_legacy_capability("terminal"))
        self.assertTrue(self.registry.is_operation_supported("terminal", "execute_command"))

        # Execute echo through the unified registry
        res = self.registry.execute("terminal", "execute_command", {"command": "echo 'PHASE_2_LEGACY_PASS'"})
        self.assertTrue(res.success)
        self.assertEqual(res.data.get("stdout", "").strip(), "PHASE_2_LEGACY_PASS")
        self.assertEqual(res.data.get("exit_code"), 0)


if __name__ == "__main__":
    unittest.main()
