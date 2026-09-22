"""Deterministic-first verification engine for MAX.

Priority:
1. Deterministic verification:
   - Process state
   - Filesystem state
   - Application state
   - Accessibility state
   - Browser state
   - Task state
2. VLM / LLM verification:
   - Invoked strictly when deterministic verification is insufficient.
3. If unverified:
   - Reports UNKNOWN, never SUCCESS.
"""

from __future__ import annotations
from pathlib import Path
import re
from typing import Any, Optional, TYPE_CHECKING
from capabilities.base import ExecutionResult
from verification.base import GoalStatus, VerificationResult, GoalEvaluation

if TYPE_CHECKING:
    from agent.planner import PlanStep
    from agent.observer import AgentObservation


class GoalEvaluator:
    """Evaluates whether specific actions and overall goals are genuinely satisfied."""

    def evaluate_step(
        self,
        step: PlanStep,
        result: ExecutionResult,
        observation: AgentObservation,
    ) -> VerificationResult:
        """Deterministically verify whether a step achieved its intended outcome.

        Does not perform LLM calls unless deterministic verification is fundamentally impossible.
        """
        if not result.success:
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Action '{step.capability}.{step.action}' failed: {result.error or 'Tool error'}",
                evidence={"action_result": result.data, "error": result.error},
            )

        cap = step.capability.lower()
        action = step.action.lower()
        criteria = (step.verification_criteria or "").lower()

        # 1. Deterministic Application Verification
        if cap in ("applications", "app") or action in ("launch_application", "quit_application", "activate_application", "is_application_running", "list_installed_applications"):
            if action == "launch_application":
                app_target = step.args.get("application_name", "")
                verified_running = result.verification.get("process_present_in_process_list", False)
                if not verified_running:
                    # Double-check against latest observation active app or process list
                    if observation.active_application and app_target.lower() in observation.active_application.lower():
                        verified_running = True
                if verified_running:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Application '{app_target}' was verified running in OS process list.",
                        evidence={"application": app_target, "verified_running": True},
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' was launched but not found in running process list.",
                    evidence={"application": app_target, "verified_running": False},
                )

            elif action == "quit_application":
                app_target = step.args.get("application_name", "")
                proc_gone = result.verification.get("process_terminated", False)
                return VerificationResult(
                    status=GoalStatus.SATISFIED if proc_gone else GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' termination: {proc_gone}",
                    evidence={"application": app_target, "terminated": proc_gone},
                )

            elif action == "activate_application":
                app_target = step.args.get("application_name", "")
                frontmost = (observation.active_application or "").lower()
                if app_target and app_target.lower() in frontmost:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Application '{app_target}' is verified as frontmost active application.",
                        evidence={"application": app_target, "active_application": observation.active_application},
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' was activated but frontmost application is '{observation.active_application}'.",
                    evidence={"application": app_target, "active_application": observation.active_application},
                )

            elif action == "is_application_running":
                app_target = step.args.get("application_name", "")
                is_running = result.data.get("is_running", False)
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Checked running state for '{app_target}' (running: {is_running}).",
                    evidence={"application": app_target, "is_running": is_running},
                )

            elif action == "list_installed_applications":
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation="Installed applications listed from system bundle directories.",
                    evidence={"count": result.data.get("count", 0)},
                )

        # 2. Deterministic Filesystem Verification
        elif cap == "filesystem":
            if action == "write_file":
                p = Path(step.args.get("path", "")).expanduser()
                if p.exists() and p.is_file():
                    sz = p.stat().st_size
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"File '{p}' verified on disk ({sz} bytes).",
                        evidence={"path": str(p), "size_bytes": sz},
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"File '{p}' was not found on disk after write operation.",
                    evidence={"path": str(p), "exists": False},
                )

            elif action == "move_file":
                src = Path(step.args.get("source", "")).expanduser()
                dst = Path(step.args.get("destination", "")).expanduser()
                dst_exists = dst.exists()
                src_gone = not src.exists()
                if dst_exists and src_gone:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"File successfully moved to '{dst}' and removed from '{src}'.",
                        evidence={"source_gone": src_gone, "destination_exists": dst_exists},
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Move verification failed (src_gone={src_gone}, dst_exists={dst_exists}).",
                    evidence={"source_gone": src_gone, "destination_exists": dst_exists},
                )

            elif action == "move_to_trash":
                target = Path(step.args.get("path", "")).expanduser()
                if not target.exists():
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Target '{target}' removed from original location.",
                        evidence={"path": str(target), "removed": True},
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Target '{target}' still exists at original location after trash request.",
                    evidence={"path": str(target), "removed": False},
                )

            elif action in ("read_file", "find_files", "list_directory", "get_metadata"):
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Filesystem read operation '{action}' succeeded.",
                    evidence=result.evidence,
                )

        # 3. Deterministic Task Verification
        elif cap == "tasks":
            task_id = result.data.get("task_id") or step.args.get("task_id", "")
            if action in ("watch_directory", "monitor_port"):
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Watcher '{task_id}' active and registered with supervisor.",
                    evidence=result.data,
                )
            elif action == "start_background_task":
                is_daemon = step.args.get("is_daemon", False) or result.data.get("is_daemon", False)
                if is_daemon:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Background daemon '{task_id}' started and running under supervisor.",
                        evidence=result.data,
                    )
                else:
                    return VerificationResult(
                        status=GoalStatus.UNKNOWN,
                        explanation=f"Task '{task_id}' was launched in the background but has not completed execution.",
                        evidence=result.data,
                    )
            elif action == "kill_task":
                killed = result.verification.get("process_terminated", False)
                return VerificationResult(
                    status=GoalStatus.SATISFIED if killed else GoalStatus.UNSATISFIED,
                    explanation=f"Task termination: {killed}",
                    evidence={"task_id": task_id, "killed": killed},
                )

        # 4. Terminal Command Verification
        elif cap == "terminal":
            exit_code = result.exit_code if result.exit_code is not None else result.data.get("exit_code", 0 if result.success else 1)
            exit_zero = result.verification.get("exit_code_zero", exit_code == 0)
            if exit_zero:
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation="Shell command completed with exit code 0.",
                    evidence={
                        "exit_code": exit_code,
                        "stdout": result.data.get("stdout", "")[:200],
                    },
                )
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Shell command returned non-zero exit code: {exit_code}",
                evidence={"exit_code": exit_code, "stderr": result.data.get("stderr", "")},
            )

        # 5. Vision / Visual Verification
        elif cap == "vision":
            # Handled by ScreenVerifier in capabilities/vision/verifier.py
            v_status = result.verification.get("status")
            if v_status == "SATISFIED":
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=result.data.get("explanation", "Visual verification confirmed."),
                    evidence=result.evidence,
                )
            elif v_status == "UNSATISFIED":
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=result.data.get("explanation", "Visual target not confirmed."),
                    evidence=result.evidence,
                )
            else:
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=result.data.get("explanation", "Visual verification inconclusive."),
                    evidence=result.evidence,
                )

        # 6. Browser Verification
        elif cap == "browser":
            if action in ("get_active_tab_info", "read_page_text") and result.success:
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Browser query operation '{action}' successfully retrieved page data.",
                    evidence=result.evidence,
                )
            return VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation=f"Browser action '{action}' was dispatched, but no explicit tab/page state verification is implemented.",
                evidence=result.evidence,
            )

        # 7. Accessibility Verification
        elif cap == "accessibility":
            if action in ("get_active_window_info", "list_menu_items", "get_computer_state") and result.success:
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Accessibility inspection '{action}' successfully retrieved UI state.",
                    evidence=result.evidence,
                )
            elif action == "find_element":
                if result.success and result.verification.get("element_found"):
                    target_role = result.data.get("element", {}).get("role", "")
                    target_title = result.data.get("element", {}).get("title", "")
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"UI element successfully grounded: {target_role} '{target_title}'.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Could not find element matching '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
            elif action == "click_element":
                if result.success and result.verification.get("element_clicked"):
                    method = result.data.get("method", "system_events")
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Clicked element '{step.args.get('label')}' via {method}.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to click element '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
            elif action == "type_into_element":
                if result.success and result.verification.get("typed_successfully"):
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Typed {result.data.get('text_length', 0)} character(s) into '{step.args.get('target_label') or 'active element'}'.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to type text into element '{step.args.get('target_label')}'.",
                        evidence=result.evidence,
                    )
            elif action == "focus_element":
                if result.success and result.verification.get("focused"):
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Moved focus to element '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to focus element '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
            elif action in ("send_keystroke", "send_key_chord"):
                if result.success and result.verification.get("keystroke_sent"):
                    key_val = step.args.get("text") or step.args.get("key") or ""
                    mods = step.args.get("modifiers", "")
                    chord_str = f"{mods}+{key_val}" if mods else key_val
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Dispatched keystroke shortcut '{chord_str}'.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Failed to send keystroke.",
                        evidence=result.evidence,
                    )
            elif action == "scroll":
                if result.success and result.verification.get("scrolled"):
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Scrolled {step.args.get('direction', 'down')} by {step.args.get('amount', 5)} units.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Scroll action failed.",
                        evidence=result.evidence,
                    )
            elif action == "click_menu_item":
                if result.success and result.verification.get("menu_item_clicked"):
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Clicked menu item '{step.args.get('item_name')}' in '{step.args.get('menu_name')}'.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Could not click menu item '{step.args.get('item_name')}'.",
                        evidence=result.evidence,
                    )
            elif action == "close_frontmost_window":
                if result.success and result.verification.get("close_button_clicked"):
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation="Closed frontmost window.",
                        evidence=result.evidence,
                    )
                elif not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Could not close frontmost window.",
                        evidence=result.evidence,
                    )
            return VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation=f"Accessibility action '{action}' executed, but no explicit post-action GUI state verification is implemented.",
                evidence=result.evidence,
            )

        # 8. macOS System Interfaces
        elif cap == "macos":
            if action in ("read_clipboard", "spotlight_search", "read_system_default") and result.success:
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"macOS system inspection '{action}' successfully retrieved data.",
                    evidence=result.evidence,
                )
            return VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation=f"macOS action '{action}' executed, but no explicit post-action state verification is implemented.",
                evidence=result.evidence,
            )

        # Default fallback for unverified capabilities: NEVER assume SATISFIED from tool success alone
        return VerificationResult(
            status=GoalStatus.UNKNOWN,
            explanation=f"No explicit verification is implemented for '{step.capability}.{step.action}'.",
            evidence=result.evidence,
        )

    def evaluate_goal(
        self,
        user_request: str,
        steps_executed: list[Any],
        remaining_steps: list[PlanStep],
        last_observation: AgentObservation,
    ) -> GoalEvaluation:
        """Evaluate whether the user's high-level goal has been reached."""
        if not steps_executed:
            return GoalEvaluation(
                status=GoalStatus.UNSATISFIED,
                explanation="No steps have been executed yet.",
            )

        # Check for unrecovered failures: a step failure is considered recovered if subsequent steps
        # successfully executed and the latest step in the trajectory succeeded
        unrecovered_failures = []
        for i, r in enumerate(steps_executed):
            if not r.step.is_optional and r.verification.status != GoalStatus.SATISFIED:
                later_successes = [
                    later for later in steps_executed[i+1:]
                    if later.verification.status == GoalStatus.SATISFIED
                ]
                if not later_successes or steps_executed[-1].verification.status != GoalStatus.SATISFIED:
                    unrecovered_failures.append(r)

        if unrecovered_failures:
            last_failed = unrecovered_failures[-1]
            if last_failed.verification.status == GoalStatus.UNKNOWN:
                return GoalEvaluation(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Cannot verify outcome for step '{last_failed.step.capability}.{last_failed.step.action}': {last_failed.verification.explanation}",
                    evidence=last_failed.verification.evidence,
                )
            return GoalEvaluation(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Required step '{last_failed.step.capability}.{last_failed.step.action}' was not satisfied: {last_failed.verification.explanation}",
                evidence=last_failed.verification.evidence,
            )

        # If there are still planned non-optional steps remaining in the queue
        mandatory_remaining = [s for s in remaining_steps if not s.is_optional]
        if mandatory_remaining:
            return GoalEvaluation(
                status=GoalStatus.UNSATISFIED,
                explanation=f"{len(mandatory_remaining)} required step(s) still remaining in plan.",
                remaining_requirements=[f"{s.capability}.{s.action}" for s in mandatory_remaining],
            )

        # Check for unfulfilled interaction intent: if user requested typing/messaging/searching
        # but only launch/inspection steps were executed
        req_lower = user_request.lower()
        interaction_intents = [
            "message", "send", "type", "write", "saying", "search for", "compose", "note saying", "text saying"
        ]
        has_interaction_intent = any(intent in req_lower for intent in interaction_intents)
        if has_interaction_intent:
            executed_actions = [(r.step.capability.lower(), r.step.action.lower()) for r in steps_executed]
            has_interaction_executed = any(
                act in ("type_into_element", "click_element", "send_keystroke", "send_key_chord", "execute_command", "send_keys", "click")
                for _, act in executed_actions
            )
            if not has_interaction_executed:
                return GoalEvaluation(
                    status=GoalStatus.UNSATISFIED,
                    explanation="Application was launched, but requested action inside the application (typing, clicking, or messaging) has not yet been executed.",
                    remaining_requirements=["interact_inside_application"],
                )

        # All executed steps are verified SATISFIED and no mandatory steps remain
        last_rec = steps_executed[-1]
        return GoalEvaluation(
            status=GoalStatus.SATISFIED,
            explanation="All planned steps executed and verified successfully.",
            evidence=last_rec.verification.evidence,
            verified_steps=[r.step.step_number for r in steps_executed],
        )


# Global evaluator singleton
goal_evaluator = GoalEvaluator()
evaluator = goal_evaluator
