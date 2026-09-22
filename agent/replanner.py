"""Replanner and diagnostic recovery engine for MAX."""

from capabilities.base import ExecutionResult
from .planner import PlanStep


class Replanner:
    """Diagnoses failures and suggests alternative execution paths."""

    def determine_recovery_step(self, failed_step: PlanStep, result: ExecutionResult) -> PlanStep | None:
        """Analyze failure and construct an adaptive fallback step if available."""
        # 1. Application launch failure -> search installed apps to find the exact name
        if failed_step.capability == "applications" and failed_step.action == "launch_application":
            app_target = failed_step.args.get("application_name", "")
            return PlanStep(
                step_number=failed_step.step_number + 1,
                capability="applications",
                action="list_installed_applications",
                args={"filter_text": app_target[:4] if len(app_target) >= 4 else app_target},
                verification_criteria="Find matching application bundle path",
                is_optional=False,
            )

        # 2. File not found in filesystem -> try searching via Spotlight or find_files
        if failed_step.capability == "filesystem" and failed_step.action in ("read_file", "get_metadata"):
            target_path = failed_step.args.get("path", "")
            target_name = target_path.split("/")[-1]
            return PlanStep(
                step_number=failed_step.step_number + 1,
                capability="macos",
                action="spotlight_search",
                args={"query": target_name, "max_results": 5},
                verification_criteria="Locate actual file path via Spotlight",
                is_optional=False,
            )

        # 3. Terminal command not found
        if failed_step.capability == "terminal" and "command not found" in (result.error or "").lower():
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

        return None
