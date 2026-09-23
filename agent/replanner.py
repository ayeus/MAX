"""State-driven replanner and diagnostic recovery engine for MAX 2.0.

Reasons from ComputerState differences, modal interruptions, target staleness,
and state deltas rather than brittle application-specific branches.
"""

from __future__ import annotations
import logging
from typing import Any, Optional

from capabilities.base import ExecutionResult
from capabilities.accessibility.models import ComputerState, UIElement
from agent.planner import PlanStep
from agent.observer import AgentObservation
from agent.goal import Goal, Subgoal, SubgoalStatus, ActionIntent, ExpectedPostcondition, PostconditionType

logger = logging.getLogger(__name__)


class Replanner:
    """Diagnoses failures and state mismatches, formulating state-driven recovery actions."""

    def diagnose_state_mismatch(
        self,
        expected_postcondition: Optional[ExpectedPostcondition],
        pre_state: Optional[ComputerState],
        post_state: Optional[ComputerState],
        result: Optional[ExecutionResult] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Classify the root cause of a failure or unexpected state transition."""
        diagnosis = {
            "type": "UNKNOWN_MISMATCH",
            "description": reason or "State mismatch detected",
            "modal_detected": False,
            "modal_title": None,
            "focus_lost": False,
            "target_stale": False,
            "partial_text": False,
            "app_switched": False,
        }

        if not post_state:
            return diagnosis

        # 1. Detect Modal / Dialog / Alert interruption
        for win in post_state.windows:
            if win.is_modal or win.subrole in ("AXDialog", "AXSheet") or "dialog" in win.title.lower() or "alert" in win.title.lower():
                diagnosis["type"] = "MODAL_INTERRUPTION"
                diagnosis["modal_detected"] = True
                diagnosis["modal_title"] = win.title
                diagnosis["description"] = f"Unexpected modal or dialog appeared: '{win.title}'"
                return diagnosis

        # 2. Detect Application or Window Focus loss
        if pre_state and post_state.active_application != pre_state.active_application:
            diagnosis["type"] = "APP_SWITCHED"
            diagnosis["app_switched"] = True
            diagnosis["description"] = f"Active application changed from '{pre_state.active_application}' to '{post_state.active_application}'"
            return diagnosis

        if expected_postcondition and expected_postcondition.expected_window:
            exp_w = expected_postcondition.expected_window.lower()
            act_w = (post_state.active_window_title or "").lower()
            if exp_w not in act_w:
                diagnosis["type"] = "WINDOW_MISMATCH"
                diagnosis["focus_lost"] = True
                diagnosis["description"] = f"Expected window '{expected_postcondition.expected_window}', but active window is '{post_state.active_window_title}'"
                return diagnosis

        if expected_postcondition and expected_postcondition.postcondition_type == PostconditionType.ELEMENT_FOCUSED:
            target_p = expected_postcondition.target_path or ""
            fe = post_state.focused_element
            if not fe or (target_p and fe.path != target_p and not fe.path.endswith(target_p.split("/")[-1])):
                diagnosis["type"] = "FOCUS_LOST"
                diagnosis["focus_lost"] = True
                diagnosis["description"] = f"Expected focus on '{target_p}', but focused element is '{fe.path if fe else 'None'}'"
                return diagnosis

        # 3. Detect Text Entry Partial or Mismatched Value
        if expected_postcondition and expected_postcondition.postcondition_type in (
            PostconditionType.TEXT_VALUE_EQUALS,
            PostconditionType.TEXT_VALUE_CONTAINS,
        ):
            target_p = expected_postcondition.target_path
            el = post_state.root_element.find_by_path(target_p) if (post_state.root_element and target_p) else None
            if not el and post_state.focused_element:
                el = post_state.focused_element
            if el:
                exp_v = expected_postcondition.expected_value or ""
                val = el.value or ""
                if exp_v not in val:
                    diagnosis["type"] = "TEXT_VALUE_MISMATCH"
                    diagnosis["partial_text"] = bool(val)
                    diagnosis["description"] = f"Text mismatch in {el.role}: expected '{exp_v}', found '{val}'"
                    return diagnosis

        # 4. Target Stale / Disappeared
        if expected_postcondition and expected_postcondition.target_path:
            target_p = expected_postcondition.target_path
            el_exists = False
            if post_state.root_element and post_state.root_element.find_by_path(target_p):
                el_exists = True
            for cand in post_state.interactive_elements:
                if cand.path == target_p:
                    el_exists = True
                    break
            if not el_exists:
                diagnosis["type"] = "TARGET_DISAPPEARED"
                diagnosis["target_stale"] = True
                diagnosis["description"] = f"Target element at '{target_p}' is no longer present in current state"
                return diagnosis

        return diagnosis

    def determine_recovery_subgoal(
        self,
        failed_subgoal: Subgoal,
        goal: Goal,
        result: ExecutionResult,
        pre_state: Optional[ComputerState],
        post_state: Optional[ComputerState],
        delta: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
    ) -> Optional[Subgoal]:
        """Formulate a recovery Subgoal based on ComputerState diagnosis."""
        diagnosis = self.diagnose_state_mismatch(
            expected_postcondition=failed_subgoal.expected_postcondition,
            pre_state=pre_state,
            post_state=post_state,
            result=result,
            reason=reason,
        )
        dtype = diagnosis["type"]

        # Strategy 1: Modal Interruption -> Address or dismiss dialog
        if dtype == "MODAL_INTERRUPTION":
            modal_title = diagnosis.get("modal_title") or "dialog"
            return Subgoal(
                description=f"Inspect and handle unexpected dialog: '{modal_title}'",
                target_description=modal_title,
                target_constraints={"role": "dialog"},
                action_intent=ActionIntent(
                    action_type="click",
                    parameters={"label": "Cancel", "role": "button", "scope_role": "dialog"},
                    expected_postcondition=ExpectedPostcondition(
                        postcondition_type=PostconditionType.WINDOW_CLOSED,
                        expected_window=modal_title,
                        description=f"Dialog '{modal_title}' dismissed",
                    ),
                ),
                expected_postcondition=ExpectedPostcondition(
                    postcondition_type=PostconditionType.WINDOW_CLOSED,
                    expected_window=modal_title,
                ),
            )

        # Strategy 2: Focus / Application Lost -> Bring target back to foreground
        if dtype == "APP_SWITCHED" and pre_state and pre_state.active_application:
            target_app = pre_state.active_application
            return Subgoal(
                description=f"Re-activate application '{target_app}'",
                target_description=target_app,
                action_intent=ActionIntent(
                    action_type="activate_application",
                    parameters={"application_name": target_app},
                    expected_postcondition=ExpectedPostcondition(
                        postcondition_type=PostconditionType.APPLICATION_RUNNING,
                        expected_application=target_app,
                    ),
                ),
                expected_postcondition=ExpectedPostcondition(
                    postcondition_type=PostconditionType.APPLICATION_RUNNING,
                    expected_application=target_app,
                ),
            )

        # Strategy 2b: Target Element Focus Lost -> Restore focus to target element
        if dtype == "FOCUS_LOST":
            target_p = failed_subgoal.expected_postcondition.target_path if failed_subgoal.expected_postcondition else ""
            target_lbl = failed_subgoal.target_description or ""
            return Subgoal(
                description=f"Restore focus to element at '{target_p or target_lbl}'",
                target_description=target_lbl,
                action_intent=ActionIntent(
                    action_type="focus",
                    parameters={"target_path": target_p, "label": target_lbl},
                    expected_postcondition=ExpectedPostcondition(
                        postcondition_type=PostconditionType.ELEMENT_FOCUSED,
                        target_path=target_p,
                    ),
                ),
                expected_postcondition=ExpectedPostcondition(
                    postcondition_type=PostconditionType.ELEMENT_FOCUSED,
                    target_path=target_p,
                ),
            )

        # Strategy 3: Text Mismatch / Partial Text -> Clear field and re-enter
        if dtype == "TEXT_VALUE_MISMATCH":
            exp_val = failed_subgoal.expected_postcondition.expected_value if failed_subgoal.expected_postcondition else ""
            target_label = failed_subgoal.target_description or ""
            return Subgoal(
                description=f"Clear input field and re-type '{exp_val}'",
                target_description=target_label,
                action_intent=ActionIntent(
                    action_type="type_text",
                    parameters={"text": exp_val, "target_label": target_label, "clear_first": True, "press_return": False},
                    expected_postcondition=ExpectedPostcondition(
                        postcondition_type=PostconditionType.TEXT_VALUE_EQUALS,
                        expected_value=exp_val,
                    ),
                ),
                expected_postcondition=ExpectedPostcondition(
                    postcondition_type=PostconditionType.TEXT_VALUE_EQUALS,
                    expected_value=exp_val,
                ),
            )

        # Strategy 4: Target Disappeared / Stale -> Re-observe and re-ground
        if dtype == "TARGET_DISAPPEARED":
            # If observation was truncated, targeted inspection is needed
            return Subgoal(
                description=f"Re-ground target '{failed_subgoal.target_description}' from fresh UI observation",
                target_description=failed_subgoal.target_description,
                target_constraints=failed_subgoal.target_constraints,
                action_intent=failed_subgoal.action_intent,
                expected_postcondition=failed_subgoal.expected_postcondition,
            )

        return None

    def determine_recovery_step(
        self,
        failed_step: PlanStep,
        result: ExecutionResult,
        observation: Optional[AgentObservation] = None,
        pre_observation: Optional[AgentObservation] = None,
        reason: Optional[str] = None,
    ) -> Optional[PlanStep]:
        """Legacy compatibility interface for PlanStep recovery."""
        cap = failed_step.capability.lower()
        action = failed_step.action.lower()

        # Check for state mismatch if ComputerState is present
        pre_cs = pre_observation.computer_state if pre_observation else None
        post_cs = observation.computer_state if observation else None

        if post_cs:
            diag = self.diagnose_state_mismatch(None, pre_cs, post_cs, result, reason)
            if diag.get("modal_detected"):
                return PlanStep(
                    step_number=failed_step.step_number + 1,
                    capability="accessibility",
                    action="click_element",
                    args={"label": "Cancel", "role": "button"},
                    verification_criteria=f"Dismiss unexpected modal dialog '{diag.get('modal_title')}'",
                )
            if diag.get("app_switched") and pre_cs and pre_cs.active_application:
                return PlanStep(
                    step_number=failed_step.step_number + 1,
                    capability="applications",
                    action="activate_application",
                    args={"application_name": pre_cs.active_application},
                    verification_criteria=f"Bring {pre_cs.active_application} back to foreground",
                )

        # Application launch recovery
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

        # Filesystem read recovery
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

        # Terminal command not found recovery
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

        # Accessibility click recovery -> re-activate application
        if cap in ("accessibility", "vision") or action in ("click_target", "activate_application"):
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


replanner = Replanner()
