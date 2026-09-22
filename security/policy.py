"""Security policy enforcement for MAX agent."""

from .risk import RiskLevel, RiskAssessment, assess_command_risk, assess_path_risk
from app.config import settings


class PolicyViolation(Exception):
    """Raised when an operation violates security policy and cannot be executed."""
    pass


class SecurityPolicy:
    """Enforces boundaries and determines confirmation requirements."""

    def __init__(
        self,
        allow_network: bool = settings.allow_network_tools,
        confirm_high_risk: bool = settings.require_confirmation_for_high_risk,
    ):
        self.allow_network = allow_network
        self.confirm_high_risk = confirm_high_risk

    def evaluate_command(self, command: str) -> RiskAssessment:
        """Evaluate a shell command string against safety rules and blocked patterns."""
        assessment = assess_command_risk(command)
        if assessment.level == RiskLevel.BLOCKED:
            raise PolicyViolation(
                f"Command execution blocked by security policy: {assessment.reason}"
            )
        return assessment

    def evaluate_path_access(self, path: str, is_destructive: bool = False) -> RiskAssessment:
        """Evaluate a file path against protected OS boundaries and deletion rules."""
        assessment = assess_path_risk(path)
        if assessment.level == RiskLevel.BLOCKED and is_destructive:
            raise PolicyViolation(
                f"Destructive operation blocked on protected path: {assessment.reason}"
            )
        return assessment

    def enforce_confirmation(self, assessment: RiskAssessment, user_confirmed: bool | None) -> bool:
        """Enforce that HIGH risk actions require affirmative user confirmation."""
        if assessment.level == RiskLevel.BLOCKED:
            raise PolicyViolation(f"Operation is BLOCKED: {assessment.reason}")
        if assessment.level == RiskLevel.HIGH and self.confirm_high_risk:
            if not user_confirmed:
                raise PolicyViolation(
                    f"HIGH-risk operation aborted: affirmative user confirmation required ({assessment.reason})"
                )
        return True
