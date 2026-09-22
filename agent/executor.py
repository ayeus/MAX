"""Executor for executing plan steps on the real Mac."""

from capabilities.registry import registry
from capabilities.base import ExecutionResult
from security.audit import audit_log
from .planner import PlanStep


class Executor:
    """Dispatches plan steps to registered capabilities and records real outcomes."""

    def execute_step(self, step: PlanStep) -> ExecutionResult:
        """Execute a single plan step via the capability registry."""
        audit_log.log_event(
            event_type="step_started",
            tool=step.capability,
            action=step.action,
            details={"step_number": step.step_number, "args": step.args},
        )

        result = registry.execute(
            capability_name=step.capability,
            action=step.action,
            args=step.args,
        )

        audit_log.log_event(
            event_type="step_completed" if result.success else "step_failed",
            tool=step.capability,
            action=step.action,
            details={
                "step_number": step.step_number,
                "success": result.success,
                "error": result.error,
                "duration_ms": result.duration_ms,
            },
            success=result.success,
        )

        return result
