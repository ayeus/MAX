"""Replanner and diagnostic recovery engine for MAX."""

from typing import Optional
from capabilities.base import ExecutionResult
from agent.planner import PlanStep
from agent.observer import AgentObservation


class Replanner:
    """Diagnoses failures and suggests alternative execution paths."""

    def determine_recovery_step(
        self,
        failed_step: PlanStep,
        result: ExecutionResult,
        observation: Optional[AgentObservation] = None,
        reason: Optional[str] = None,
    ) -> PlanStep | None:
        """Analyze failure or state mismatch and construct an adaptive fallback step.

        Triggers when:
        1. Action failed (result.success is False), OR
        2. Action succeeded, BUT expected state was not achieved.
        """
        cap = failed_step.capability.lower()
        action = failed_step.action.lower()

        # 1. Application launch failure or unverified running
        if cap == "applications" and action == "launch_application":
            app_target = failed_step.args.get("application_name", "")
            return PlanStep(
                step_number=failed_step.step_number + 1,
                capability="applications",
                action="list_installed_applications",
                args={"filter_text": app_target[:4] if len(app_target) >= 4 else app_target},
                verification_criteria="Find matching application bundle path",
                is_optional=False,
            )

        # 2. File not found in filesystem -> search via Spotlight or find_files
        if cap == "filesystem" and action in ("read_file", "get_metadata"):
            target_path = failed_step.args.get("path", "")
            target_name = target_path.split("/")[-1] if target_path else ""
            return PlanStep(
                step_number=failed_step.step_number + 1,
                capability="macos",
                action="spotlight_search",
                args={"query": target_name, "max_results": 5},
                verification_criteria="Locate actual file path via Spotlight",
                is_optional=False,
            )

        # 3. Terminal command not found
        if cap == "terminal" and "command not found" in (result.error or "").lower():
            cmd = failed_step.args.get("command", "")
            binary = cmd.split()[0] if cmd else ""
            return PlanStep(
                step_number=failed_step.step_number + 1,
                capability="terminal",
                action="check_tool_installed",
                args={"tool_name": binary},
                verification_criteria="Verify whether binary exists on PATH",
                is_optional=True,
            )

        # 4. Action succeeded but UI/window state was not achieved (e.g. click/activate didn't focus window)
        if cap in ("accessibility", "vision") or action in ("click_target", "activate_application"):
            # If target app is known, attempt to activate it via system
            app_target = failed_step.args.get("application_name") or (observation.active_application if observation else None)
            if app_target:
                return PlanStep(
                    step_number=failed_step.step_number + 1,
                    capability="applications",
                    action="activate_application",
                    args={"application_name": app_target},
                    verification_criteria=f"Bring {app_target} to foreground",
                    is_optional=False,
                )

        return None
