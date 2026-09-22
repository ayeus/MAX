"""Core agent orchestration loop for MAX."""

import json
import threading
from pydantic import BaseModel, Field
from typing import Any, Optional
from .observer import observer
from .context import assemble_context, AgentContext
from .planner import Planner, Plan, PlanStep
from .executor import Executor
from .replanner import Replanner
from capabilities import initialize_default_capabilities
from capabilities.base import ExecutionResult
from verification import GoalStatus, AgentState, GoalEvaluation, VerificationResult, goal_evaluator


class StepExecutionRecord(BaseModel):
    step: PlanStep
    result: ExecutionResult
    observation_after: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationResult


class AgentExecutionReport(BaseModel):
    user_request: str
    thought: str
    steps_executed: list[StepExecutionRecord]
    final_summary: str
    state: AgentState
    goal_evaluation: GoalEvaluation
    overall_success: bool
    limitations: list[str] = Field(default_factory=list)


class AgentCore:
    """Orchestrates the deterministic-first closed-loop computer control cycle on macOS."""

    def __init__(self, planner: Planner | None = None, executor: Executor | None = None):
        initialize_default_capabilities()
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.replanner = Replanner()
        self.state: AgentState = AgentState.IDLE
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Propagate user cancellation across the active agent loop."""
        self._cancel_event.set()
        self.state = AgentState.CANCELLED

    def run(self, user_request: str, debug: bool = False) -> AgentExecutionReport:
        """Execute a natural-language computer outcome request with closed-loop verification."""
        self._cancel_event.clear()
        self.state = AgentState.PLANNING

        # 1. Observe & Assemble Context
        context = assemble_context()

        # 2. Plan
        plan = self.planner.create_plan(user_request, context)

        executed_records: list[StepExecutionRecord] = []
        limitations: list[str] = []
        steps_queue = list(plan.plan)
        replan_count = 0
        max_replans = 3
        max_steps = 15
        step_count = 0

        goal_eval = GoalEvaluation(
            status=GoalStatus.UNSATISFIED,
            explanation="Execution started.",
        )

        # 3. Closed-Loop Step Execution
        while step_count < max_steps:
            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                limitations.append("Execution was cancelled by user.")
                break

            # If steps queue is empty, check if high-level goal requires continuation planning
            if not steps_queue:
                if goal_eval.status == GoalStatus.SATISFIED:
                    self.state = AgentState.DONE
                    break

                if replan_count < max_replans and executed_records:
                    self.state = AgentState.PLANNING
                    replan_count += 1
                    fresh_context = assemble_context(
                        recent_history=[
                            {
                                "step": r.step.model_dump(),
                                "success": r.result.success,
                                "observation": r.observation_after,
                            }
                            for r in executed_records
                        ],
                        fast=False,
                    )
                    continuation_prompt = (
                        f"Goal: {user_request}\n"
                        f"Steps already completed successfully: {[f'{r.step.capability}.{r.step.action}' for r in executed_records]}\n"
                        f"Current active application: {fresh_context.observation.active_application}\n"
                        f"Current active window: {fresh_context.observation.active_window}\n"
                        f"Formulate the next concrete steps (e.g. typing text, clicking buttons, shortcuts) to fulfill the outcome."
                    )
                    continuation_plan = self.planner.create_plan(continuation_prompt, fresh_context)
                    if continuation_plan and continuation_plan.plan:
                        steps_queue.extend(continuation_plan.plan)
                        continue
                    else:
                        limitations.append("Planner produced no subsequent steps to complete remaining goal.")
                        break
                else:
                    break

            step = steps_queue.pop(0)
            step_count += 1

            # EXECUTING
            self.state = AgentState.EXECUTING
            res = self.executor.execute_step(step)

            # OBSERVING: Fast demand-driven observation, capturing UI state after app/GUI actions
            self.state = AgentState.OBSERVING
            is_gui_action = step.capability in ("applications", "accessibility")
            post_obs = observer.observe(fast=not is_gui_action, include_ui=is_gui_action)

            # VERIFYING: Deterministic-first verification
            self.state = AgentState.VERIFYING
            step_verif = goal_evaluator.evaluate_step(step, res, post_obs)

            record = StepExecutionRecord(
                step=step,
                result=res,
                observation_after={
                    "active_application": post_obs.active_application,
                    "active_window": post_obs.active_window,
                    "current_directory": post_obs.current_directory,
                },
                verification=step_verif,
            )
            executed_records.append(record)

            # Evaluate overall goal progress
            goal_eval = goal_evaluator.evaluate_goal(
                user_request=user_request,
                steps_executed=executed_records,
                remaining_steps=steps_queue,
                last_observation=post_obs,
            )

            # If goal is satisfied, terminate immediately
            if goal_eval.status == GoalStatus.SATISFIED:
                self.state = AgentState.DONE
                break

            # Handle step failure or unsatisfied verification
            if step_verif.status != GoalStatus.SATISFIED and not step.is_optional:
                if replan_count < max_replans:
                    self.state = AgentState.REPLANNING
                    replan_count += 1
                    recovery_step = self.replanner.determine_recovery_step(
                        failed_step=step,
                        result=res,
                        observation=post_obs,
                        reason=step_verif.explanation,
                    )
                    if recovery_step:
                        steps_queue.insert(0, recovery_step)
                    else:
                        limitations.append(f"Step {step.step_number} ({step.capability}.{step.action}): {step_verif.explanation}")
                else:
                    limitations.append(f"Exceeded maximum replan limit ({max_replans}) on step {step.step_number}.")
                    self.state = AgentState.FAILED
                    break

        # Final state resolution
        if self._cancel_event.is_set():
            self.state = AgentState.CANCELLED
            goal_eval = GoalEvaluation(
                status=GoalStatus.UNKNOWN,
                explanation="Operation was cancelled before goal verification could complete.",
            )
        elif goal_eval.status == GoalStatus.SATISFIED:
            self.state = AgentState.DONE
        elif goal_eval.status == GoalStatus.UNKNOWN:
            self.state = AgentState.FAILED
        else:
            self.state = AgentState.FAILED

        overall_success = (goal_eval.status == GoalStatus.SATISFIED)

        # 4. Synthesize Final Factual Summary based strictly on real evidence
        final_summary = self._generate_evidence_summary(
            user_request=user_request,
            records=executed_records,
            goal_eval=goal_eval,
            state=self.state,
            limitations=limitations,
        )

        return AgentExecutionReport(
            user_request=user_request,
            thought=plan.thought,
            steps_executed=executed_records,
            final_summary=final_summary,
            state=self.state,
            goal_evaluation=goal_eval,
            overall_success=overall_success,
            limitations=limitations,
        )

    def _generate_evidence_summary(
        self,
        user_request: str,
        records: list[StepExecutionRecord],
        goal_eval: GoalEvaluation,
        state: AgentState,
        limitations: list[str],
    ) -> str:
        """Produce an honest, factual summary answering: Was the user's requested outcome achieved?"""
        lines = [
            f"Goal: {user_request}",
            f"Status: {goal_eval.status.value} (State: {state.value})",
            "",
            f"Goal Evaluation: {goal_eval.explanation}",
        ]

        if records:
            lines.append("\nActions Executed:")
            for r in records:
                step = r.step
                res = r.result
                verif = r.verification
                icon = "✓" if verif.status == GoalStatus.SATISFIED else ("?" if verif.status == GoalStatus.UNKNOWN else "✗")

                if step.capability == "terminal" and step.action == "execute_command":
                    cmd = step.args.get("command", "")
                    code = res.exit_code if res.exit_code is not None else (res.data.get("exit_code") if res.data else 0)
                    lines.append(f"  {icon} Command `{cmd}` (exit {code}): {verif.explanation}")
                elif step.capability == "applications" and step.action == "launch_application":
                    app = step.args.get("application_name", "")
                    lines.append(f"  {icon} Launch `{app}`: {verif.explanation}")
                elif step.capability == "filesystem":
                    lines.append(f"  {icon} Filesystem {step.action}: {verif.explanation}")
                else:
                    lines.append(f"  {icon} {step.capability}.{step.action}: {verif.explanation}")

        if limitations:
            lines.append("\nLimitations / Notes:")
            for lim in limitations:
                lines.append(f"  - {lim}")

        return "\n".join(lines)
