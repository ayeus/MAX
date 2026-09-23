"""Core agent orchestration loop for MAX 2.0 closed-loop computer-use engine."""

from __future__ import annotations
import json
import logging
import threading
from typing import Any, Optional
from pydantic import BaseModel, Field

from .observer import observer, AgentObservation, ObservationTier
from .context import assemble_context, AgentContext
from .planner import Planner, Plan, PlanStep
from .executor import Executor
from .replanner import Replanner
from .goal import Goal, Subgoal, SubgoalStatus, ActionIntent, ExpectedPostcondition, PostconditionType, TargetReference
from .perception import perception_pipeline, PerceptionMethod
from .latency import latency_tracker, LatencyReport
from capabilities import initialize_default_capabilities
from capabilities.base import ExecutionResult
from capabilities.accessibility.grounding import TargetConstraints
from capabilities.accessibility.models import TargetValidity
from verification import GoalStatus, AgentState, GoalEvaluation, VerificationResult, goal_evaluator

logger = logging.getLogger(__name__)


class StepExecutionRecord(BaseModel):
    step: PlanStep
    result: ExecutionResult
    observation_after: dict[str, Any] = Field(default_factory=dict)
    verification: VerificationResult


class ComputerUseTraceItem(BaseModel):
    step_number: int
    subgoal_id: Optional[str] = None
    subgoal_description: Optional[str] = None
    target_description: Optional[str] = None
    grounding_method: Optional[str] = None
    grounding_evidence: dict[str, Any] = Field(default_factory=dict)
    action: str
    action_args: dict[str, Any] = Field(default_factory=dict)
    action_success: bool
    state_delta_summary: list[str] = Field(default_factory=list)
    postcondition_type: Optional[str] = None
    verification_status: str
    verification_explanation: str
    replan_reason: Optional[str] = None


class ComputerUseTrace(BaseModel):
    goal: str
    items: list[ComputerUseTraceItem] = Field(default_factory=list)
    final_status: str = "UNKNOWN"


class AgentExecutionReport(BaseModel):
    user_request: str
    thought: str
    steps_executed: list[StepExecutionRecord]
    final_summary: str
    state: AgentState
    goal_evaluation: GoalEvaluation
    overall_success: bool
    limitations: list[str] = Field(default_factory=list)
    trace: Optional[ComputerUseTrace] = None
    goal_model: Optional[Goal] = None
    latency_report: Optional[LatencyReport] = None



class AgentCore:
    """Orchestrates the state-driven closed-loop computer control cycle on macOS."""

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

        trace = ComputerUseTrace(goal=user_request)

        latency_tracker.mark_planning_start()
        # 1. Observe & Assemble Context (fast tier to avoid cold planning latency)
        context = assemble_context(fast=True)

        # 2. Plan
        plan = self.planner.create_plan(user_request, context)
        latency_tracker.mark_planning_end()

        if self._cancel_event.is_set():
            self.state = AgentState.CANCELLED
            trace.final_status = "CANCELLED"
            latency_tracker.mark_completion()
            return AgentExecutionReport(
                user_request=user_request,
                thought="Cancelled during planning",
                steps_executed=[],
                final_summary=f"Goal: {user_request}\nStatus: UNKNOWN (State: CANCELLED)",
                state=self.state,
                goal_evaluation=GoalEvaluation(status=GoalStatus.UNKNOWN, explanation="Execution was cancelled by user."),
                overall_success=False,
                limitations=["Execution was cancelled by user."],
                trace=trace,
                latency_report=latency_tracker.current,
            )

        # If planner failed or returned no steps
        if not plan.plan:
            thought_l = (plan.thought or "").lower()
            is_unsupported = any(
                w in thought_l
                for w in (
                    "not supported", "cannot perform", "can't perform", "unsupported",
                    "no registered capability", "don't have a supported", "not have a supported"
                )
            )

            if is_unsupported:
                self.state = AgentState.UNSUPPORTED
                goal_eval = GoalEvaluation(
                    status=GoalStatus.UNSUPPORTED,
                    explanation=plan.thought or f"I don't have a supported capability to perform '{user_request}'.",
                )
                trace.final_status = "UNSUPPORTED"
                latency_tracker.mark_completion()
                return AgentExecutionReport(
                    user_request=user_request,
                    thought=plan.thought,
                    steps_executed=[],
                    final_summary=f"Goal: {user_request}\nStatus: UNSUPPORTED\n\n{goal_eval.explanation}",
                    state=self.state,
                    goal_evaluation=goal_eval,
                    overall_success=False,
                    limitations=[goal_eval.explanation],
                    trace=trace,
                    latency_report=latency_tracker.current,
                )
            else:
                self.state = AgentState.FAILED
                goal_eval = GoalEvaluation(
                    status=GoalStatus.UNSATISFIED,
                    explanation=plan.thought or f"Unable to formulate plan for '{user_request}'",
                )
                trace.final_status = "FAILED"
                latency_tracker.mark_completion()
                return AgentExecutionReport(
                    user_request=user_request,
                    thought=plan.thought,
                    steps_executed=[],
                    final_summary=f"Goal: {user_request}\nStatus: UNSATISFIED (State: FAILED)\n\nGoal Evaluation: {goal_eval.explanation}",
                    state=self.state,
                    goal_evaluation=goal_eval,
                    overall_success=False,
                    limitations=["Planner produced no executable steps."],
                    trace=trace,
                    latency_report=latency_tracker.current,
                )

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

            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                limitations.append("Execution was cancelled by user.")
                break

            # PRE-OBSERVATION (authoritative baseline for state delta)
            is_gui_action = step.capability in ("applications", "accessibility", "vision")
            tier = ObservationTier.STANDARD if is_gui_action else ObservationTier.FAST
            pre_obs = observer.observe(tier=tier)

            # EXECUTING
            self.state = AgentState.EXECUTING
            latency_tracker.mark_execution_start()
            res = self.executor.execute_step(step)
            latency_tracker.mark_first_action_dispatched()

            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                limitations.append("Execution was cancelled by user.")
                record = StepExecutionRecord(
                    step=step,
                    result=res,
                    observation_after={
                        "active_application": pre_obs.active_application if pre_obs else "",
                        "active_window": pre_obs.active_window if pre_obs else "",
                        "current_directory": pre_obs.current_directory if pre_obs else "",
                    },
                    verification=VerificationResult(status=GoalStatus.UNKNOWN, explanation="Step executed, but execution was cancelled by user."),
                )
                executed_records.append(record)
                break

            # POST-OBSERVATION: capture immediate post-action state
            self.state = AgentState.OBSERVING
            post_obs = observer.observe(tier=tier, force_refresh=True)

            # Compute State Delta
            delta_summary = []
            if pre_obs.computer_state and post_obs.computer_state:
                delta = pre_obs.computer_state.compute_delta(post_obs.computer_state)
                if delta.get("app_changed"):
                    delta_summary.append(f"app_switched: {pre_obs.computer_state.active_application} -> {post_obs.computer_state.active_application}")
                if delta.get("window_changed"):
                    delta_summary.append(f"window_changed: {pre_obs.computer_state.active_window_title} -> {post_obs.computer_state.active_window_title}")
                if delta.get("focus_changed"):
                    delta_summary.append("focus_changed")
                if delta.get("value_changes"):
                    delta_summary.append(f"{len(delta['value_changes'])} value(s) updated")
                if delta.get("added_interactive_controls", 0) > 0:
                    delta_summary.append(f"+{delta['added_interactive_controls']} controls")
                if delta.get("removed_interactive_controls", 0) > 0:
                    delta_summary.append(f"-{delta['removed_interactive_controls']} controls")

            # VERIFYING: Deterministic-first verification comparing pre/post state
            self.state = AgentState.VERIFYING
            step_verif = goal_evaluator.evaluate_step(step, res, post_obs, pre_observation=pre_obs)
            latency_tracker.mark_first_verification()

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

            # Record trace item
            trace.items.append(
                ComputerUseTraceItem(
                    step_number=step_count,
                    action=f"{step.capability}.{step.action}",
                    action_args=step.args,
                    action_success=res.success,
                    state_delta_summary=delta_summary,
                    verification_status=step_verif.status.value,
                    verification_explanation=step_verif.explanation,
                )
            )

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

            # Handle step failure or unsatisfied verification -> State-Driven Replanning
            if step_verif.status != GoalStatus.SATISFIED and not step.is_optional:
                if replan_count < max_replans:
                    self.state = AgentState.REPLANNING
                    replan_count += 1
                    recovery_step = self.replanner.determine_recovery_step(
                        failed_step=step,
                        result=res,
                        observation=post_obs,
                        pre_observation=pre_obs,
                        reason=step_verif.explanation,
                    )
                    if recovery_step:
                        trace.items[-1].replan_reason = f"Recovery scheduled: {recovery_step.capability}.{recovery_step.action}"
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
            trace.final_status = "CANCELLED"
        elif goal_eval.status == GoalStatus.SATISFIED:
            self.state = AgentState.DONE
            trace.final_status = "SATISFIED"
        elif goal_eval.status == GoalStatus.UNKNOWN:
            self.state = AgentState.FAILED
            trace.final_status = "UNKNOWN"
        else:
            self.state = AgentState.FAILED
            trace.final_status = "FAILED"

        overall_success = (goal_eval.status == GoalStatus.SATISFIED)

        # Synthesize Final Factual Summary based strictly on real evidence
        final_summary = self._generate_evidence_summary(
            user_request=user_request,
            records=executed_records,
            goal_eval=goal_eval,
            state=self.state,
            limitations=limitations,
        )

        latency_tracker.mark_completion()
        return AgentExecutionReport(
            user_request=user_request,
            thought=plan.thought,
            steps_executed=executed_records,
            final_summary=final_summary,
            state=self.state,
            goal_evaluation=goal_eval,
            overall_success=overall_success,
            limitations=limitations,
            trace=trace,
            latency_report=latency_tracker.current,
        )

    def execute_goal(self, goal: Goal, max_steps: int = 15) -> AgentExecutionReport:
        """Execute a structured Goal model with closed-loop Subgoal grounding and verification."""
        self._cancel_event.clear()
        self.state = AgentState.EXECUTING

        trace = ComputerUseTrace(goal=goal.objective)
        executed_records: list[StepExecutionRecord] = []
        limitations: list[str] = []
        step_count = 0
        replan_count = 0
        max_replans = 3

        while not goal.is_complete() and step_count < max_steps:
            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                goal.status = SubgoalStatus.CANCELLED
                limitations.append("Execution cancelled by user.")
                break

            subgoal = goal.get_current_subgoal()
            if not subgoal:
                break

            step_count += 1

            # 1. Pre-Observation
            pre_obs = observer.observe(fast=False, include_ui=True, force_refresh=True)
            pre_cs = pre_obs.computer_state

            # 2. Target Grounding (if target constraints specified and no valid target reference)
            grounding_evidence: dict[str, Any] = {}
            grounding_method = "DIRECT"

            if subgoal.target_constraints and pre_cs:
                constraints = TargetConstraints(**subgoal.target_constraints)
                perception_res = perception_pipeline.resolve_target(constraints, pre_cs)

                if perception_res.is_ambiguous:
                    subgoal.status = SubgoalStatus.UNSATISFIED
                    subgoal.evidence["ambiguity"] = perception_res.rationale
                    limitations.append(f"Ambiguous target for subgoal '{subgoal.description}': {perception_res.rationale}")
                    goal.fail_current_subgoal(f"Ambiguous target: {perception_res.rationale}")
                    break

                if perception_res.is_usable:
                    grounding_method = perception_res.method.value if subgoal.attempts == 0 else f"REGROUNDED_{perception_res.method.value}"
                    grounding_evidence = perception_res.evidence
                    if perception_res.target_ref and subgoal.action_intent:
                        subgoal.action_intent.target_ref = perception_res.target_ref
                else:
                    subgoal.status = SubgoalStatus.UNSATISFIED
                    limitations.append(f"Target unresolved for subgoal '{subgoal.description}': {perception_res.rationale}")
                    goal.fail_current_subgoal(f"Target unresolved: {perception_res.rationale}")
                    break
            elif subgoal.action_intent and subgoal.action_intent.target_ref and pre_cs:
                # Revalidate existing target reference against fresh current state
                val_status, validated_el, val_reason = subgoal.action_intent.target_ref.validate_in(pre_cs)
                if val_status == TargetValidity.VALID and validated_el:
                    grounding_method = "REVALIDATED_SAME_TARGET"
                    grounding_evidence = {"validity": val_status.value, "reason": val_reason, "target_path": validated_el.path}
                elif val_status == TargetValidity.AMBIGUOUS:
                    subgoal.status = SubgoalStatus.UNSATISFIED
                    goal.fail_current_subgoal(f"TargetReference is ambiguous in current state: {val_reason}")
                    break
                elif val_status == TargetValidity.STALE:
                    subgoal.status = SubgoalStatus.UNSATISFIED
                    goal.fail_current_subgoal(f"TargetReference is stale: {val_reason}")
                    break

            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                goal.status = SubgoalStatus.CANCELLED
                break

            # 3. Action Dispatch
            intent = subgoal.action_intent
            res: ExecutionResult
            if intent:
                from capabilities.registry import registry
                act_type = intent.action_type.lower()
                params = dict(intent.parameters)
                if intent.target_ref and intent.target_ref.path and "target_path" not in params:
                    params["target_path"] = intent.target_ref.path

                if act_type in ("click", "click_element"):
                    res = registry.get("accessibility").execute("click_element", params)
                elif act_type in ("type", "type_text", "type_into_element"):
                    res = registry.get("accessibility").execute("type_into_element", params)
                elif act_type in ("focus", "focus_element"):
                    res = registry.get("accessibility").execute("focus_element", params)
                elif act_type in ("key_chord", "shortcut", "send_key_chord"):
                    res = registry.get("accessibility").execute("send_key_chord", params)
                elif act_type in ("activate_application", "launch_application"):
                    res = registry.get("applications").execute(act_type, params)
                elif act_type == "execute_command":
                    res = registry.get("terminal").execute("execute_command", params)
                else:
                    res = ExecutionResult(success=False, capability="agent", action=act_type, error=f"Unknown action intent '{act_type}'")
            else:
                res = ExecutionResult(success=True, capability="agent", action="noop", data={"note": "Inspection subgoal"})

            if self._cancel_event.is_set():
                self.state = AgentState.CANCELLED
                goal.status = SubgoalStatus.CANCELLED
                break

            # 4. Post-Observation
            post_obs = observer.observe(fast=False, include_ui=True, force_refresh=True)
            post_cs = post_obs.computer_state

            # Compute State Delta
            delta_summary = []
            if pre_cs and post_cs:
                delta = pre_cs.compute_delta(post_cs)
                if delta.get("app_changed"):
                    delta_summary.append("app_changed")
                if delta.get("window_changed"):
                    delta_summary.append("window_changed")
                if delta.get("focus_changed"):
                    delta_summary.append("focus_changed")
                if delta.get("value_changes"):
                    delta_summary.append(f"{len(delta['value_changes'])} value(s) changed")

            # 5. Postcondition Verification
            if subgoal.expected_postcondition:
                step_verif = goal_evaluator.evaluate_postcondition(
                    postcondition=subgoal.expected_postcondition,
                    pre_state=pre_cs,
                    post_state=post_cs,
                    result=res,
                )
            else:
                # Mutating GUI actions MUST NOT become SATISFIED without an explicit expected postcondition
                act_str = (intent.action_type.value if hasattr(intent.action_type, "value") else str(intent.action_type)).lower() if intent else ""
                mutating_actions = {
                    "click", "double_click", "right_click", "focus", "focus_element",
                    "type_text", "type_into_element", "replace_text", "press_key",
                    "send_keystroke", "key_chord", "send_key_chord", "scroll",
                    "select", "send", "submit", "click_element"
                }
                if act_str in mutating_actions or (res.action and res.action in mutating_actions):
                    if not res.success:
                        step_verif = VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=res.error or f"Mutating action '{act_str}' failed.",
                            evidence=res.evidence,
                        )
                    else:
                        step_verif = VerificationResult(
                            status=GoalStatus.UNKNOWN,
                            explanation=f"Mutating action '{act_str}' reported dispatch success, but has no explicit verifiable postcondition.",
                            evidence=res.evidence,
                        )
                else:
                    step_verif = VerificationResult(
                        status=GoalStatus.SATISFIED if res.success else GoalStatus.UNSATISFIED,
                        explanation="Action completed." if res.success else res.error or "Action failed.",
                        evidence=res.evidence,
                    )

            # Record step
            pseudo_step = PlanStep(
                step_number=step_count,
                capability="agent",
                action=intent.action_type if intent else "inspect",
                args=intent.parameters if intent else {},
            )
            rec = StepExecutionRecord(
                step=pseudo_step,
                result=res,
                observation_after={"active_app": post_obs.active_application, "active_win": post_obs.active_window},
                verification=step_verif,
            )
            executed_records.append(rec)

            trace.items.append(
                ComputerUseTraceItem(
                    step_number=step_count,
                    subgoal_id=subgoal.id,
                    subgoal_description=subgoal.description,
                    target_description=subgoal.target_description,
                    grounding_method=grounding_method,
                    grounding_evidence=grounding_evidence,
                    action=intent.action_type if intent else "inspect",
                    action_args=intent.parameters if intent else {},
                    action_success=res.success,
                    state_delta_summary=delta_summary,
                    postcondition_type=subgoal.expected_postcondition.postcondition_type.value if subgoal.expected_postcondition else None,
                    verification_status=step_verif.status.value,
                    verification_explanation=step_verif.explanation,
                )
            )

            # 6. Advance or Replan
            if step_verif.status == GoalStatus.SATISFIED:
                goal.advance_subgoal()
            else:
                subgoal.attempts += 1
                if subgoal.attempts < subgoal.max_attempts and replan_count < max_replans:
                    replan_count += 1
                    recovery = self.replanner.determine_recovery_subgoal(
                        failed_subgoal=subgoal,
                        goal=goal,
                        result=res,
                        pre_state=pre_cs,
                        post_state=post_cs,
                        delta=pre_cs.compute_delta(post_cs) if (pre_cs and post_cs) else None,
                        reason=step_verif.explanation,
                    )
                    if recovery:
                        trace.items[-1].replan_reason = f"Recovery subgoal inserted: {recovery.description}"
                        goal.subgoals.insert(goal.current_subgoal_index, recovery)
                        continue

                goal.fail_current_subgoal(step_verif.explanation)
                break

        overall_success = (goal.status == SubgoalStatus.SATISFIED)
        trace.final_status = goal.status.value

        goal_eval = GoalEvaluation(
            status=GoalStatus.SATISFIED if overall_success else GoalStatus.UNSATISFIED,
            explanation="All subgoals satisfied." if overall_success else f"Goal stopped at subgoal {goal.current_subgoal_index + 1}/{len(goal.subgoals)}.",
        )

        final_summary = self._generate_evidence_summary(
            user_request=goal.objective,
            records=executed_records,
            goal_eval=goal_eval,
            state=self.state,
            limitations=limitations,
        )

        return AgentExecutionReport(
            user_request=goal.objective,
            thought=f"Closed-loop goal execution: {goal.objective}",
            steps_executed=executed_records,
            final_summary=final_summary,
            state=self.state,
            goal_evaluation=goal_eval,
            overall_success=overall_success,
            limitations=limitations,
            trace=trace,
            goal_model=goal,
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
