"""Canonical Capability & Operation Models for MAX Dynamic Capability Platform.

Provides strongly typed models and taxonomies for:
- Capability vs. Operation hierarchy
- Availability states
- Required permissions
- Risk classification
- Generic capability execution constraints
- Verification contracts
- Provenance
- Provider characteristics and health
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict

from security.risk import RiskLevel


class AvailabilityStatus(str, Enum):
    """Explicit lifecycle availability states for capabilities and operations."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_INSTALLED = "NOT_INSTALLED"
    DISABLED = "DISABLED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class AvailabilityInfo(BaseModel):
    """Structured availability state with diagnostic reason and timestamp."""

    status: AvailabilityStatus = AvailabilityStatus.UNKNOWN
    reason: Optional[str] = None
    missing_permissions: list[str] = Field(default_factory=list)
    checked_at: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class RequiredPermission(BaseModel):
    """Declaration of a system or platform permission required by an operation."""

    name: str
    description: Optional[str] = None
    system_settings_path: Optional[str] = None
    is_optional: bool = False
    status: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class CapabilityRisk(BaseModel):
    """Structured risk classification for an operation."""

    level: RiskLevel = RiskLevel.LOW
    description: str = ""
    requires_confirmation: bool = False
    affected_targets: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class ConstraintType(str, Enum):
    """Categorization of generic operational execution constraints."""

    REQUIRED_PERMISSION = "REQUIRED_PERMISSION"
    OS_VERSION = "OS_VERSION"
    REQUIRED_APPLICATION = "REQUIRED_APPLICATION"
    PROVIDER_STATE = "PROVIDER_STATE"
    ENVIRONMENT = "ENVIRONMENT"
    INPUT_RANGE = "INPUT_RANGE"
    TARGET_TYPE = "TARGET_TYPE"


class CapabilityConstraint(BaseModel):
    """Generic structured execution prerequisite evaluated against live context."""

    constraint_type: ConstraintType
    parameter: str
    expected_value: Any
    description: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

    def evaluate(self, context: dict[str, Any]) -> tuple[bool, Optional[str]]:
        """Evaluate if the constraint is satisfied given runtime context."""
        val = context.get(self.parameter)
        if val is None:
            return False, f"Missing context parameter '{self.parameter}' for constraint '{self.description or self.constraint_type.value}'"

        if isinstance(self.expected_value, list):
            if val not in self.expected_value:
                return False, f"Context '{self.parameter}'={val} not in expected set {self.expected_value}"
            return True, None

        if val != self.expected_value:
            return False, f"Context '{self.parameter}'={val} does not match expected {self.expected_value}"

        return True, None


class VerificationStrategy(str, Enum):
    """Categories of independent verification mechanisms available for operations."""

    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    FILESYSTEM_OBSERVATION = "FILESYSTEM_OBSERVATION"
    ACCESSIBILITY_OBSERVATION = "ACCESSIBILITY_OBSERVATION"
    PROCESS_OBSERVATION = "PROCESS_OBSERVATION"
    BROWSER_OBSERVATION = "BROWSER_OBSERVATION"
    TERMINAL_OBSERVATION = "TERMINAL_OBSERVATION"
    MODEL_ASSISTED = "MODEL_ASSISTED"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class VerificationContract(BaseModel):
    """Contract describing how an operation's postcondition can be independently verified.

    Critical invariant: Absence of verification or VerificationStrategy.NONE never implies SATISFIED.
    """

    strategy: VerificationStrategy = VerificationStrategy.UNKNOWN
    is_verifiable: bool = True
    independent_observer_required: bool = False
    observer_source: Optional[str] = None
    expected_evidence_type: Optional[str] = None
    verification_availability: AvailabilityStatus = AvailabilityStatus.AVAILABLE
    description: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class CapabilityProvenance(BaseModel):
    """Real provenance tracing a capability to its discovery source without fabrication."""

    provider_id: str
    discovery_mechanism: str
    source_identifier: Optional[str] = None
    source_version: Optional[str] = None
    discovered_at: Optional[str] = None
    environment: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class CapabilityVersion(BaseModel):
    """Semantic versioning for capability contracts and providers."""

    version: str = "1.0.0"
    provider_version: str = "1.0.0"
    schema_version: str = "1.0.0"

    model_config = ConfigDict(extra="ignore")


class ProviderHealth(BaseModel):
    """Readiness and health status of a capability provider."""

    healthy: bool = True
    message: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")


class ProviderCharacteristics(BaseModel):
    """Structured provider characteristics to enable future evidence-based provider selection."""

    reliability_score: float = 1.0
    expected_latency_tier: str = "FAST"
    verification_quality: str = "HIGH"
    risk_level: RiskLevel = RiskLevel.LOW
    provider_type: str = "NATIVE"
    health: ProviderHealth = Field(default_factory=ProviderHealth)

    model_config = ConfigDict(extra="ignore")


class OperationDescriptor(BaseModel):
    """Descriptor for an individual action/operation on a capability."""

    operation_id: str
    capability_id: str
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    availability: AvailabilityInfo = Field(
        default_factory=lambda: AvailabilityInfo(status=AvailabilityStatus.AVAILABLE)
    )
    permissions: list[RequiredPermission] = Field(default_factory=list)
    constraints: list[CapabilityConstraint] = Field(default_factory=list)
    risk: CapabilityRisk = Field(default_factory=CapabilityRisk)
    verification: VerificationContract = Field(default_factory=VerificationContract)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    @property
    def qualified_id(self) -> str:
        """Fully-qualified canonical operation identity: <capability_id>.<operation_id>."""
        return f"{self.capability_id}.{self.operation_id}"


class CapabilityDescriptor(BaseModel):
    """Canonical descriptor for a logical capability (WHAT MAX can operate on)."""

    capability_id: str
    name: str
    description: str
    domain: str = "system"
    operations: dict[str, OperationDescriptor] = Field(default_factory=dict)
    provider_id: str
    version: CapabilityVersion = Field(default_factory=CapabilityVersion)
    provenance: Optional[CapabilityProvenance] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="ignore")

    def get_operation(self, operation_id: str) -> Optional[OperationDescriptor]:
        """Retrieve operation by operation_id."""
        return self.operations.get(operation_id)

    def add_operation(self, op: OperationDescriptor) -> None:
        """Register operation under this capability."""
        self.operations[op.operation_id] = op
