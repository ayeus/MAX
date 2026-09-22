"""Core agent orchestration loop for MAX."""

import json
from pydantic import BaseModel, Field
from typing import Any
from .observer import observer
from .context import assemble_context, AgentContext
from .planner import Planner, Plan, PlanStep
from .executor import Executor
from .replanner import Replanner
from capabilities import initialize_default_capabilities
from capabilities.base import ExecutionResult
from llm.prompts import build_evaluation_prompt
from llm.model_manager import model_manager


class StepExecutionRecord(BaseModel):
    step: PlanStep
    result: ExecutionResult
    observation_after: dict[str, Any] = Field(default_factory=dict)


class AgentExecutionReport(BaseModel):
    user_request: str
    thought: str
    steps_executed: list[StepExecutionRecord]
    final_summary: str
    overall_success: bool
    limitations: list[str] = Field(default_factory=list)


class AgentCore:
    """Orchestrates the closed-loop computer control cycle on macOS."""

    def __init__(self, planner: Planner | None = None, executor: Executor | None = None):
        initialize_default_capabilities()
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.replanner = Replanner()

    def run(self, user_request: str, debug: bool = False) -> AgentExecutionReport:
        """Execute a natural-language computer outcome request."""
        # 1. Observe & Assemble Context
        context = assemble_context()

        # 2. Plan
        plan = self.planner.create_plan(user_request, context)

        executed_records: list[StepExecutionRecord] = []
        overall_success = True
        limitations: list[str] = []

        # 3. Closed-Loop Step Execution
        steps_queue = list(plan.plan)
        step_idx = 0
        max_steps = 15

        while steps_queue and step_idx < max_steps:
            step = steps_queue.pop(0)
            step_idx += 1

            # Execute
            res = self.executor.execute_step(step)

            # Observe post-execution state
            post_obs = observer.observe()

            record = StepExecutionRecord(
                step=step,
                result=res,
                observation_after={
                    "active_application": post_obs.active_application,
                    "current_directory": post_obs.current_directory,
                },
            )
            executed_records.append(record)

            # Verify & Adapt
            if not res.success:
                if not step.is_optional:
                    overall_success = False

                # Check if replanner can offer a recovery step
                recovery_step = self.replanner.determine_recovery_step(step, res)
                if recovery_step:
                    steps_queue.insert(0, recovery_step)
                else:
                    if res.error:
                        limitations.append(f"Step {step.step_number} ({step.capability}.{step.action}): {res.error}")

        # 4. Synthesize Final Factual Summary based strictly on real evidence
        final_summary = self._generate_evidence_summary(user_request, executed_records, overall_success)

        return AgentExecutionReport(
            user_request=user_request,
            thought=plan.thought,
            steps_executed=executed_records,
            final_summary=final_summary,
            overall_success=overall_success,
            limitations=limitations,
        )

    def _generate_evidence_summary(
        self,
        user_request: str,
        records: list[StepExecutionRecord],
        overall_success: bool,
    ) -> str:
        """Produce an honest, factual summary of actual results from execution evidence."""
        if not records:
            return "No actions were performed."

        # Collect real outputs and statuses
        summary_lines = []
        for r in records:
            step = r.step
            res = r.result
            status_icon = "✓" if res.success else "✗"

            if step.capability == "terminal" and step.action == "execute_command":
                cmd = step.args.get("command", "")
                stdout = res.data.get("stdout", "").strip()
                stderr = res.data.get("stderr", "").strip()
                out = stdout or stderr or "(no output)"
                summary_lines.append(f"{status_icon} Executed `{cmd}`: {out}")

            elif step.capability == "applications" and step.action == "launch_application":
                app = step.args.get("application_name", "")
                verified = res.verification.get("process_present_in_process_list", False)
                if verified:
                    summary_lines.append(f"{status_icon} Launched {app} and verified it is running.")
                else:
                    summary_lines.append(f"{status_icon} Requested launch of {app}, but process was not verified in running list.")

            elif step.capability == "filesystem":
                action = step.action
                if action == "find_files":
                    count = res.data.get("matches_count", 0)
                    matches = res.data.get("matches", [])
                    names = ", ".join(m["name"] for m in matches[:5])
                    extra = f" (including {names})" if names else ""
                    summary_lines.append(f"{status_icon} Found {count} matching file(s){extra}.")
                elif action == "list_directory":
                    count = res.data.get("count", 0)
                    summary_lines.append(f"{status_icon} Listed directory: {count} items found.")
                elif action == "read_file":
                    p = step.args.get("path", "")
                    content = res.data.get("content", "").strip()
                    summary_lines.append(f"{status_icon} Read `{p}` ({res.data.get('lines_read', 0)} lines).")
                else:
                    summary_lines.append(f"{status_icon} {action} completed on filesystem.")

            else:
                summary_lines.append(f"{status_icon} {step.capability}.{step.action} executed.")

        return "\n".join(summary_lines)
