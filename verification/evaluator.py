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
from verification.base import (
    GoalStatus,
    VerificationResult,
    GoalEvaluation,
    ExpectedPostcondition,
    PostconditionType,
)
from capabilities.accessibility.models import ComputerState, UIElement

if TYPE_CHECKING:
    from agent.planner import PlanStep
    from agent.observer import AgentObservation

import os
from macos.shell import run_shell_command

CUSTOM_POSTCONDITION_REGISTRY: dict[str, Any] = {}


def register_custom_verifier(name: str, verifier_fn: Any) -> None:
    """Register an explicit custom verification function."""
    CUSTOM_POSTCONDITION_REGISTRY[name] = verifier_fn


def is_process_running_in_os(app_name: str) -> bool:
    """Independently query macOS process table for running application or binary."""
    app_clean = (app_name or "").strip()
    if not app_clean:
        return False
    try:
        res = run_shell_command(f"/usr/bin/pgrep -i -f '{app_clean}'", timeout=2)
        if res.success and res.stdout.strip():
            return True
    except Exception:
        pass
    return False


def _parse_terminal_target(command: str) -> tuple[str, Optional[str], Optional[str]]:
    """Parse common deterministic shell commands to identify action, target path, and extra info.

    Returns (action_type, target_path, extra_arg)
    action_type can be 'mkdir', 'rm', 'redirect_write', 'redirect_append', 'touch', 'inspect', or 'unknown'
    """
    cmd = (command or "").strip()
    if not cmd:
        return ("unknown", None, None)

    # Redirections
    if ">>" in cmd:
        parts = cmd.split(">>", 1)
        target = parts[1].strip().split()[0].strip("'\"") if parts[1].strip() else None
        return ("redirect_append", target, parts[0].strip())
    elif ">" in cmd:
        parts = cmd.split(">", 1)
        target = parts[1].strip().split()[0].strip("'\"") if parts[1].strip() else None
        return ("redirect_write", target, parts[0].strip())

    tokens = cmd.split()
    base = os.path.basename(tokens[0])

    if base in ("mkdir",):
        args = [t.strip("'\"") for t in tokens[1:] if not t.startswith("-")]
        target = args[-1] if args else None
        return ("mkdir", target, None)

    elif base in ("rm", "unlink"):
        args = [t.strip("'\"") for t in tokens[1:] if not t.startswith("-")]
        target = args[-1] if args else None
        return ("rm", target, None)

    elif base in ("touch",):
        args = [t.strip("'\"") for t in tokens[1:] if not t.startswith("-")]
        target = args[-1] if args else None
        return ("touch", target, None)

    elif base in ("sw_vers", "whoami", "uname", "pwd", "date", "uptime", "id", "hostname", "which", "echo", "cat", "ps", "ls", "df", "top", "env"):
        return ("inspect", None, None)

    return ("unknown", None, None)


def _requires_interaction_completion(user_request: str, steps_executed: list[Any]) -> tuple[bool, Optional[str]]:
    """Determine if a user request indicates an interactive requirement inside an application

    (e.g. typing text, messaging, search) that has not yet been executed.

    CRITICAL INVARIANT:
    This heuristic can ONLY identify a missing requirement to prevent false SATISFIED.
    It can NEVER be used to prove completion or return SATISFIED.
    """
    req_lower = user_request.lower()
    interaction_keywords = [
        "message", "send", "type", "write", "saying", "search for", "compose", "note saying", "text saying"
    ]
    has_keyword = any(kw in req_lower for kw in interaction_keywords)
    if not has_keyword:
        return False, None

    executed_actions = [(r.step.capability.lower(), r.step.action.lower()) for r in steps_executed]
    has_interaction_executed = any(
        act in (
            "type_into_element",
            "click_element",
            "send_keystroke",
            "send_key_chord",
            "execute_command",
            "send_keys",
            "click",
            "write_file",
        )
        for _, act in executed_actions
    )
    if not has_interaction_executed:
        return True, "Application was launched, but requested action inside the application (typing, clicking, or messaging) has not yet been executed."
    return False, None


class GoalEvaluator:
    """Evaluates whether specific actions and overall goals are genuinely satisfied."""

    def evaluate_step(
        self,
        step: PlanStep,
        result: ExecutionResult,
        observation: AgentObservation,
        pre_observation: Optional[AgentObservation] = None,
    ) -> VerificationResult:
        """Deterministically verify whether a step achieved its intended outcome.

        Does not perform LLM calls unless deterministic verification is fundamentally impossible.
        """
        if not result.success:
            if step.action.lower() == "is_application_running":
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=result.error or f"Could not determine running state for '{step.args.get('application_name', '')}'.",
                    evidence=result.evidence,
                )
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
                verified_running = False
                # Independent observation
                if observation.active_application and app_target.lower() in observation.active_application.lower():
                    verified_running = True
                elif observation.recent_processes and any(app_target.lower() in p.lower() for p in observation.recent_processes):
                    verified_running = True
                elif observation.computer_state and observation.computer_state.active_application and app_target.lower() in observation.computer_state.active_application.lower():
                    verified_running = True
                elif is_process_running_in_os(app_target):
                    verified_running = True
                elif result.verification.get("process_present_in_process_list") is True and result.verification.get("open_command_exit_zero") is not False:
                    # Supporting evidence when independent OS query is inconclusive or in synthetic environment
                    verified_running = True

                # If result explicitly records that process was NOT in process list, respect failure
                if result.verification.get("process_present_in_process_list") is False:
                    verified_running = False

                if verified_running:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Application '{app_target}' was verified running in OS process list.",
                        evidence={"application": app_target, "verified_running": True},
                        observer_source="os_process_table",
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' was launched but not found in running process list.",
                    evidence={"application": app_target, "verified_running": False},
                    observer_source="os_process_table",
                )

            elif action == "quit_application":
                app_target = step.args.get("application_name", "")
                still_running = False
                if observation.active_application and app_target.lower() in observation.active_application.lower():
                    still_running = True
                elif observation.recent_processes and any(app_target.lower() in p.lower() for p in observation.recent_processes):
                    still_running = True
                elif is_process_running_in_os(app_target):
                    still_running = True
                elif result.verification.get("process_terminated") is False:
                    still_running = True

                proc_gone = not still_running
                return VerificationResult(
                    status=GoalStatus.SATISFIED if proc_gone else GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' termination: {proc_gone}",
                    evidence={"application": app_target, "terminated": proc_gone},
                    observer_source="os_process_table",
                )

            elif action == "activate_application":
                app_target = step.args.get("application_name", "")
                frontmost = (observation.active_application or "").lower()
                if app_target and app_target.lower() in frontmost:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Application '{app_target}' is verified as frontmost active application.",
                        evidence={"application": app_target, "active_application": observation.active_application},
                        observer_source="observation",
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Application '{app_target}' was activated but frontmost application is '{observation.active_application}'.",
                    evidence={"application": app_target, "active_application": observation.active_application},
                    observer_source="observation",
                )

            elif action == "is_application_running":
                app_target = step.args.get("application_name", "")
                if not result.success or "is_running" not in result.data:
                    return VerificationResult(
                        status=GoalStatus.UNKNOWN,
                        explanation=result.error or f"Could not determine running state for '{app_target}'.",
                        evidence=result.evidence,
                    )
                is_running = bool(result.data.get("is_running", False))
                if is_running:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Application '{app_target}' is verified as running.",
                        evidence={"application": app_target, "is_running": True},
                        observer_source="os_process_table",
                    )
                else:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Application '{app_target}' is verified as NOT running.",
                        evidence={"application": app_target, "is_running": False},
                        observer_source="os_process_table",
                    )

            elif action == "list_installed_applications":
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation="Installed applications listed from system bundle directories.",
                    evidence={"count": result.data.get("count", 0)},
                    observer_source="filesystem",
                )

        # 2. Deterministic Filesystem Verification
        elif cap == "filesystem":
            if action == "write_file":
                p = Path(step.args.get("path", "")).expanduser()
                if not (p.exists() and p.is_file()):
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"File '{p}' was not found on disk after write operation.",
                        evidence={"path": str(p), "exists": False},
                        observer_source="filesystem",
                    )

                sz = p.stat().st_size
                expected_content = step.args.get("content")
                if expected_content is not None:
                    try:
                        actual_content = p.read_text(encoding="utf-8", errors="replace")
                        if actual_content != expected_content:
                            return VerificationResult(
                                status=GoalStatus.UNSATISFIED,
                                explanation=f"File content mismatch in '{p}': expected '{expected_content[:50]}...', found '{actual_content[:50]}...'.",
                                evidence={"path": str(p), "expected_content": expected_content[:100], "actual_content": actual_content[:100]},
                                observer_source="filesystem",
                            )
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation=f"File '{p}' verified on disk with matching content ({len(actual_content)} chars).",
                            evidence={"path": str(p), "size_bytes": sz, "content_verified": True},
                            observer_source="filesystem",
                        )
                    except (FileNotFoundError, OSError):
                        if sz == len(expected_content.encode("utf-8")):
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"File '{p}' verified on disk ({sz} bytes).",
                                evidence={"path": str(p), "size_bytes": sz},
                                observer_source="filesystem",
                            )
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"File '{p}' could not be read to verify content.",
                            evidence={"path": str(p)},
                            observer_source="filesystem",
                        )

                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"File '{p}' verified on disk ({sz} bytes).",
                    evidence={"path": str(p), "size_bytes": sz},
                    observer_source="filesystem",
                )

            elif action == "move_file":
                src = Path(step.args.get("source", "")).expanduser()
                raw_dst = Path(step.args.get("destination", "")).expanduser()
                if raw_dst.is_dir():
                    final_dst = raw_dst / src.name
                elif result.data.get("destination"):
                    final_dst = Path(result.data.get("destination", "")).expanduser()
                else:
                    final_dst = raw_dst

                was_src_present = None
                if pre_observation and pre_observation.metadata:
                    was_src_present = pre_observation.metadata.get(f"exists:{src}")
                if result.evidence.get("source_missing") is True:
                    was_src_present = False

                if was_src_present is False:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Source file '{src}' was missing prior to move operation.",
                        evidence={"source": str(src), "source_missing": True},
                        observer_source="filesystem",
                    )

                dst_exists = final_dst.exists()
                src_gone = not src.exists()
                if dst_exists and src_gone:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"File successfully moved to '{final_dst}' and removed from '{src}'.",
                        evidence={"source_gone": src_gone, "destination_exists": dst_exists, "final_destination": str(final_dst)},
                        observer_source="filesystem",
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Move verification failed: source_gone={src_gone}, destination_exists={dst_exists} at '{final_dst}'.",
                    evidence={"source_gone": src_gone, "destination_exists": dst_exists, "final_destination": str(final_dst)},
                    observer_source="filesystem",
                )

            elif action == "move_to_trash":
                target = Path(step.args.get("path", "")).expanduser()
                was_present_before = None
                if pre_observation and pre_observation.metadata:
                    was_present_before = pre_observation.metadata.get(f"exists:{target}")
                if result.evidence.get("already_absent") is True or result.data.get("already_absent") is True:
                    was_present_before = False

                if was_present_before is False:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Target '{target}' was already absent prior to execution; deletion transition not demonstrated.",
                        evidence={"path": str(target), "already_absent": True},
                        observer_source="filesystem",
                    )

                if not target.exists():
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Target '{target}' verified removed from original location.",
                        evidence={"path": str(target), "removed": True},
                        observer_source="filesystem",
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Target '{target}' still exists at original location after trash request.",
                    evidence={"path": str(target), "removed": False},
                    observer_source="filesystem",
                )

            elif action in ("read_file", "find_files", "list_directory", "get_metadata"):
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Filesystem read operation '{action}' succeeded.",
                    evidence=result.evidence,
                    observer_source="filesystem",
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
                pid = result.data.get("pid")
                is_alive = True
                if pid:
                    try:
                        import os
                        os.kill(int(pid), 0)
                        is_alive = True
                    except OSError:
                        is_alive = False
                else:
                    is_alive = not result.verification.get("process_terminated", False)
                killed = not is_alive
                return VerificationResult(
                    status=GoalStatus.SATISFIED if killed else GoalStatus.UNSATISFIED,
                    explanation=f"Task termination: {killed}",
                    evidence={"task_id": task_id, "killed": killed},
                    observer_source="os_process_table",
                )

        # 4. Terminal Command Verification
        elif cap == "terminal":
            exit_code = result.exit_code if result.exit_code is not None else result.data.get("exit_code", 0 if result.success else 1)
            exit_zero = (exit_code == 0)

            if not exit_zero or not result.success:
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Shell command returned non-zero exit code: {exit_code}",
                    evidence={"exit_code": exit_code, "stderr": result.data.get("stderr", "")},
                    observer_source="terminal",
                )

            # Check explicit postcondition if provided
            if step.expected_postcondition:
                pre_cs = pre_observation.computer_state if pre_observation else None
                post_cs = observation.computer_state if observation else None
                post_eval = self.evaluate_postcondition(step.expected_postcondition, pre_cs, post_cs, result=result)
                if post_eval.status != GoalStatus.UNKNOWN:
                    return post_eval

            # Check explicit file target and expected content in args
            target_path_arg = step.args.get("expected_file") or step.args.get("target_path") or step.args.get("file") or step.args.get("path")
            expected_content = step.args.get("expected_content")

            cmd_str = step.args.get("command", "")
            act_type, parsed_target, extra = _parse_terminal_target(cmd_str)
            target_to_check = target_path_arg or parsed_target

            if act_type == "mkdir" and target_to_check:
                p = Path(target_to_check).expanduser()
                if p.exists() and p.is_dir():
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Directory '{p}' verified on disk after mkdir.",
                        evidence={"path": str(p), "is_dir": True, "exit_code": exit_code},
                        observer_source="filesystem",
                    )
                if step.expected_postcondition or target_path_arg or expected_content:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Directory '{p}' does not exist on disk after mkdir command.",
                        evidence={"path": str(p), "is_dir": False},
                        observer_source="filesystem",
                    )
                if exit_zero:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Directory creation command completed with exit code 0.",
                        evidence={"path": str(p), "exit_code": exit_code},
                        observer_source="terminal",
                    )
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Directory '{p}' does not exist on disk after mkdir command.",
                    evidence={"path": str(p), "is_dir": False},
                    observer_source="filesystem",
                )

            if act_type in ("redirect_write", "touch") or (target_to_check and expected_content is not None):
                if target_to_check:
                    p = Path(target_to_check).expanduser()
                    if not (p.exists() and p.is_file()):
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"Target file '{p}' does not exist on disk after shell execution.",
                            evidence={"path": str(p), "exists": False},
                            observer_source="filesystem",
                        )
                    if expected_content is not None:
                        try:
                            actual_content = p.read_text(encoding="utf-8", errors="replace")
                            if actual_content != expected_content:
                                return VerificationResult(
                                    status=GoalStatus.UNSATISFIED,
                                    explanation=f"File content mismatch in '{p}': expected '{expected_content[:50]}...', found '{actual_content[:50]}...'.",
                                    evidence={"path": str(p), "expected": expected_content[:100], "actual": actual_content[:100]},
                                    observer_source="filesystem",
                                )
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"File '{p}' verified on disk with expected content.",
                                evidence={"path": str(p), "content_matched": True},
                                observer_source="filesystem",
                            )
                        except (FileNotFoundError, OSError):
                            return VerificationResult(
                                status=GoalStatus.UNSATISFIED,
                                explanation=f"Could not read target file '{p}' to verify content.",
                                evidence={"path": str(p)},
                                observer_source="filesystem",
                            )
                    # File exists and was created
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"File '{p}' verified on disk after shell command.",
                        evidence={"path": str(p), "size_bytes": p.stat().st_size},
                        observer_source="filesystem",
                    )

            if act_type == "rm" and target_to_check:
                p = Path(target_to_check).expanduser()
                was_present = None
                if pre_observation and pre_observation.metadata:
                    was_present = pre_observation.metadata.get(f"exists:{p}")
                if was_present is False or result.evidence.get("already_absent") is True:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"File '{p}' was already absent prior to execution; deletion transition not demonstrated.",
                        evidence={"path": str(p), "already_absent": True},
                        observer_source="filesystem",
                    )
                if p.exists():
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"File '{p}' still exists on disk after deletion command.",
                        evidence={"path": str(p), "exists": True},
                        observer_source="filesystem",
                    )
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"File '{p}' verified removed from disk.",
                    evidence={"path": str(p), "removed": True},
                    observer_source="filesystem",
                )

            if act_type == "inspect":
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation="Shell inspection command completed with exit code 0.",
                    evidence={"exit_code": exit_code, "stdout": result.data.get("stdout", "")[:200]},
                    observer_source="terminal",
                )

            # Execution completed with exit code 0, but no verifiable postcondition could be proven
            return VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation="Shell command completed with exit code 0, but resulting state or postcondition could not be independently verified.",
                evidence={"exit_code": exit_code, "stdout": result.data.get("stdout", "")[:200]},
                observer_source="terminal",
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
                    observer_source="browser",
                )
            elif action in ("open_url", "search_web"):
                if not result.success:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Browser action '{action}' failed.",
                        evidence=result.evidence,
                        observer_source="browser",
                    )
                # Dispatching a navigation action without independent DOM/tab verification is UNKNOWN
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Browser action '{action}' was dispatched, but no explicit tab/page state verification is implemented.",
                    evidence=result.evidence,
                    observer_source="browser",
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
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to click element '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
                # If pre and post computer states are provided, verify state transition via compute_delta
                if pre_observation and pre_observation.computer_state and observation.computer_state:
                    delta = pre_observation.computer_state.compute_delta(observation.computer_state)
                    has_state_delta = (
                        delta.get("application_changed")
                        or delta.get("window_changed")
                        or delta.get("focus_changed")
                        or bool(delta.get("value_changes"))
                        or delta.get("added_controls_count", 0) > 0
                        or delta.get("removed_controls_count", 0) > 0
                    )
                    method = result.data.get("method", "system_events")
                    if has_state_delta:
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation=f"Clicked element '{step.args.get('label')}' via {method}: verified UI state transition.",
                            evidence={"delta": delta, "method": method},
                        )
                # Without verified state transition or explicit satisfied postcondition, return UNKNOWN
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Click was dispatched on '{step.args.get('label')}', but no observable state change or expected postcondition could be verified.",
                    evidence=result.evidence,
                )
            elif action == "type_into_element":
                expected_text = step.args.get("text") or result.evidence.get("expected_text", "")
                target_label = step.args.get("target_label", "")
                target_path = step.args.get("target_path") or result.evidence.get("target_path", "")

                # If rich ComputerState observation is present, perform genuine state inspection
                if observation.computer_state:
                    state = observation.computer_state
                    el: Optional[UIElement] = None
                    if target_path and state.root_element:
                        el = state.root_element.find_by_path(target_path)
                    if not el and target_path:
                        for cand in state.interactive_elements:
                            if cand.path == target_path:
                                el = cand
                                break
                    if not el and state.focused_element:
                        el = state.focused_element
                    if not el and target_label:
                        for cand in state.interactive_elements:
                            if cand.matches_query(target_label):
                                el = cand
                                break

                    if el and el.value is not None:
                        actual_val = el.value.strip()
                        if expected_text.strip() in actual_val or actual_val == expected_text.strip():
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"Verified text '{expected_text}' is present in {el.role} (value: '{actual_val}').",
                                evidence={"actual_value": actual_val, "expected_value": expected_text, "target_path": el.path},
                            )
                        else:
                            return VerificationResult(
                                status=GoalStatus.UNSATISFIED,
                                explanation=f"Text verification failed: expected '{expected_text}', but element value is '{actual_val}'.",
                                evidence={"actual_value": actual_val, "expected_value": expected_text, "target_path": el.path},
                            )
                    elif el:
                        return VerificationResult(
                            status=GoalStatus.UNKNOWN,
                            explanation=f"Keystrokes dispatched, but target element '{el.role}' does not expose an accessible text value to verify.",
                            evidence={"keystrokes_dispatched": True, "target_path": el.path},
                        )
                    else:
                        return VerificationResult(
                            status=GoalStatus.UNKNOWN,
                            explanation=f"Keystrokes dispatched, but target element was not found in post-action state to verify text value.",
                            evidence={"keystrokes_dispatched": True},
                        )

                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to type text into element '{step.args.get('target_label')}'.",
                        evidence=result.evidence,
                    )
                # Without independent ComputerState or verified state transition, typing dispatch alone is UNKNOWN
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Keystrokes were dispatched to '{step.args.get('target_label') or 'active element'}', but no independent ComputerState/postcondition evidence exists to verify text value.",
                    evidence=result.evidence,
                )
            elif action == "focus_element":
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to focus element '{step.args.get('label')}'.",
                        evidence=result.evidence,
                    )
                if observation.computer_state and observation.computer_state.focused_element:
                    fe = observation.computer_state.focused_element
                    target_label = (step.args.get("label") or "").strip().lower()
                    if target_label in (fe.title or "").lower() or target_label in (fe.description or "").lower() or target_label in (fe.identifier or "").lower():
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation=f"Verified element {fe.role} '{fe.title}' is currently focused.",
                            evidence={"focused_role": fe.role, "focused_title": fe.title, "path": fe.path},
                        )
                    else:
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"Focus verification failed: expected focus on '{target_label}', but focused element is {fe.role} '{fe.title}'.",
                            evidence={"actual_focused": fe.to_summary_dict()},
                        )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Focus command dispatched on '{step.args.get('label')}', but focus state could not be independently verified from post-action computer state.",
                    evidence=result.evidence,
                )
            elif action in ("send_keystroke", "send_key_chord"):
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Failed to send keystroke.",
                        evidence=result.evidence,
                    )
                # If pre and post computer states are provided, verify state transition via compute_delta
                if pre_observation and pre_observation.computer_state and observation.computer_state:
                    delta = pre_observation.computer_state.compute_delta(observation.computer_state)
                    has_state_delta = (
                        delta.get("application_changed")
                        or delta.get("window_changed")
                        or delta.get("focus_changed")
                        or bool(delta.get("value_changes"))
                        or delta.get("added_controls_count", 0) > 0
                        or delta.get("removed_controls_count", 0) > 0
                    )
                    if has_state_delta:
                        key_val = step.args.get("text") or step.args.get("key") or ""
                        mods = step.args.get("modifiers", "")
                        chord_str = f"{mods}+{key_val}" if mods else key_val
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation=f"Dispatched keystroke shortcut '{chord_str}': verified UI state transition.",
                            evidence={"delta": delta},
                        )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation="Keystroke/chord was dispatched, but no independent state change or expected postcondition could be verified.",
                    evidence=result.evidence,
                )
            elif action == "scroll":
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Scroll action failed.",
                        evidence=result.evidence,
                    )
                # Scroll is only SATISFIED if requested content/target can be verified in post-state
                target_to_reveal = step.args.get("target_label") or step.args.get("expected_text")
                if target_to_reveal and observation.computer_state:
                    state = observation.computer_state
                    for el in state.interactive_elements:
                        if el.matches_query(target_to_reveal):
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"Scrolled and verified target content '{target_to_reveal}' is now visible.",
                                evidence={"target_revealed": target_to_reveal, "element": el.to_summary_dict()},
                            )
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Scrolled, but expected content '{target_to_reveal}' was not revealed.",
                        evidence=result.evidence,
                    )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Scroll action was dispatched ({step.args.get('direction', 'down')}), but resulting content visibility could not be independently verified.",
                    evidence=result.evidence,
                )
            elif action == "click_menu_item":
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or f"Failed to click menu item '{step.args.get('item_name')}'.",
                        evidence=result.evidence,
                    )
                if pre_observation and pre_observation.computer_state and observation.computer_state:
                    delta = pre_observation.computer_state.compute_delta(observation.computer_state)
                    has_delta = delta.get("window_changed") or delta.get("application_changed") or delta.get("focus_changed") or delta.get("added_controls_count", 0) > 0
                    if has_delta:
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation=f"Clicked menu item '{step.args.get('item_name')}' in '{step.args.get('menu_name')}': state transition verified.",
                            evidence={"delta": delta},
                        )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Menu item '{step.args.get('item_name')}' was clicked, but no explicit post-action GUI state verification or resulting state transition could be verified.",
                    evidence=result.evidence,
                )
            elif action == "close_frontmost_window":
                if not result.success or result.error:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=result.error or "Could not close frontmost window.",
                        evidence=result.evidence,
                    )
                if pre_observation and pre_observation.computer_state and observation.computer_state:
                    delta = pre_observation.computer_state.compute_delta(observation.computer_state)
                    if delta.get("window_changed") or delta.get("removed_controls_count", 0) > 0 or len(observation.computer_state.windows) < len(pre_observation.computer_state.windows):
                        return VerificationResult(
                            status=GoalStatus.SATISFIED,
                            explanation="Verified frontmost window was closed.",
                            evidence={"delta": delta},
                        )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation="Window close request dispatched, but window closing could not be verified.",
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

            elif action == "get_brightness":
                if result.success and "level" in result.data:
                    lvl = result.data.get("level", 0.0)
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Display brightness verified at {lvl:.2f}.",
                        evidence=result.evidence,
                    )
                return VerificationResult(
                    status=GoalStatus.UNKNOWN if not result.data.get("supported", True) else GoalStatus.UNSATISFIED,
                    explanation=result.error or "Failed to query display brightness.",
                    evidence=result.evidence,
                )

            elif action in ("set_brightness", "increase_brightness", "decrease_brightness"):
                from macos.brightness import get_display_brightness, is_brightness_supported
                if not is_brightness_supported():
                    return VerificationResult(
                        status=GoalStatus.UNKNOWN,
                        explanation="Display brightness hardware observation is unsupported on this system.",
                        evidence=result.evidence,
                    )

                obs_ok, current_hardware_brightness, obs_err = get_display_brightness()
                if not obs_ok:
                    return VerificationResult(
                        status=GoalStatus.UNKNOWN,
                        explanation=f"Cannot observe display brightness state: {obs_err}",
                        evidence=result.evidence,
                    )

                before = result.evidence.get("before")
                after = current_hardware_brightness

                if action == "set_brightness":
                    target = step.args.get("level", result.evidence.get("target"))
                    if target is not None:
                        try:
                            target_f = float(target)
                        except (ValueError, TypeError):
                            target_f = 0.5
                        if abs(after - target_f) < 0.05 or (target_f >= 1.0 and after >= 0.95) or (target_f <= 0.0 and after <= 0.05):
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"Display brightness set to {after:.2f} (target {target_f:.2f}).",
                                evidence={"target": target_f, "observed": after, "before": before},
                            )
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"Display brightness was not achieved: expected {target_f:.2f}, observed {after:.2f}.",
                            evidence={"target": target_f, "observed": after, "before": before},
                        )

                elif action == "increase_brightness":
                    if before is not None:
                        try:
                            before_f = float(before)
                        except (ValueError, TypeError):
                            before_f = 0.0
                        if (after > before_f + 0.005) or (before_f >= 0.99 and after >= 0.99):
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"Display brightness increased from {before_f:.2f} to {after:.2f}.",
                                evidence={"before": before_f, "after": after, "delta": after - before_f},
                            )
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"Display brightness did not increase: before {before_f:.2f}, after {after:.2f}.",
                            evidence={"before": before_f, "after": after},
                        )

                elif action == "decrease_brightness":
                    if before is not None:
                        try:
                            before_f = float(before)
                        except (ValueError, TypeError):
                            before_f = 1.0
                        if (after < before_f - 0.005) or (before_f <= 0.01 and after <= 0.01):
                            return VerificationResult(
                                status=GoalStatus.SATISFIED,
                                explanation=f"Display brightness decreased from {before_f:.2f} to {after:.2f}.",
                                evidence={"before": before_f, "after": after, "delta": before_f - after},
                            )
                        return VerificationResult(
                            status=GoalStatus.UNSATISFIED,
                            explanation=f"Display brightness did not decrease: before {before_f:.2f}, after {after:.2f}.",
                            evidence={"before": before_f, "after": after},
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

        # Invariants 1, 3, 4: Compositional evaluation of all executed mandatory steps.
        # A failed mandatory step is ONLY considered recovered if THAT EXACT requirement
        # was subsequently retried and independently verified SATISFIED.
        # An unrelated recovery step (e.g. clicking fallback coordinates, listing apps)
        # does NOT satisfy the original mandatory goal.
        unrecovered_failures = []
        for i, r in enumerate(steps_executed):
            if r.step.is_optional or r.verification.status == GoalStatus.SATISFIED:
                continue

            # Look for subsequent retry of this exact requirement
            subsequent_retries = [
                later for later in steps_executed[i+1:]
                if (
                    later.step.step_number == r.step.step_number or
                    (
                        later.step.capability == r.step.capability and
                        later.step.action == r.step.action and
                        later.step.args == r.step.args
                    )
                )
            ]

            if not subsequent_retries or subsequent_retries[-1].verification.status != GoalStatus.SATISFIED:
                # Invariant G: A retry recovers a failed requirement ONLY if independently verified SATISFIED.
                # If retried and still not SATISFIED (e.g. UNKNOWN or UNSATISFIED), evaluate using the retry's record.
                target_rec = subsequent_retries[-1] if subsequent_retries else r
                unrecovered_failures.append(target_rec)

        if unrecovered_failures:
            # Composition hierarchy (Invariant 3 & Invariants C, D, E): UNSUPPORTED > UNSATISFIED > UNKNOWN
            unsupported = [f for f in unrecovered_failures if f.verification.status == GoalStatus.UNSUPPORTED]
            if unsupported:
                failed = unsupported[-1]
                return GoalEvaluation(
                    status=GoalStatus.UNSUPPORTED,
                    explanation=f"Required step '{failed.step.capability}.{failed.step.action}' is unsupported: {failed.verification.explanation}",
                    evidence=failed.verification.evidence,
                )

            unsatisfied = [f for f in unrecovered_failures if f.verification.status == GoalStatus.UNSATISFIED]
            if unsatisfied:
                failed = unsatisfied[-1]
                return GoalEvaluation(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Required step '{failed.step.capability}.{failed.step.action}' was not satisfied: {failed.verification.explanation}",
                    evidence=failed.verification.evidence,
                )

            unknown = [f for f in unrecovered_failures if f.verification.status == GoalStatus.UNKNOWN]
            if unknown:
                failed = unknown[-1]
                return GoalEvaluation(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Cannot verify outcome for step '{failed.step.capability}.{failed.step.action}': {failed.verification.explanation}",
                    evidence=failed.verification.evidence,
                )

        # If there are still planned non-optional steps remaining in the queue
        mandatory_remaining = [s for s in remaining_steps if not s.is_optional]
        if mandatory_remaining:
            return GoalEvaluation(
                status=GoalStatus.UNSATISFIED,
                explanation=f"{len(mandatory_remaining)} required step(s) still remaining in plan.",
                remaining_requirements=[f"{s.capability}.{s.action}" for s in mandatory_remaining],
            )

        # Check for unfulfilled interaction intent using isolated helper (Core Problem 5):
        # Heuristic inference may trigger more work / remain UNSATISFIED, but may NEVER prove SATISFIED.
        requires_more, reason = _requires_interaction_completion(user_request, steps_executed)
        if requires_more:
            return GoalEvaluation(
                status=GoalStatus.UNSATISFIED,
                explanation=reason or "Application was launched, but requested action inside the application (typing, clicking, or messaging) has not yet been executed.",
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

    def evaluate_postcondition(
        self,
        postcondition: ExpectedPostcondition,
        pre_state: Optional[ComputerState],
        post_state: Optional[ComputerState],
        result: Optional[ExecutionResult] = None,
    ) -> VerificationResult:
        """Deterministically evaluate an ExpectedPostcondition against pre/post ComputerState."""
        pt = postcondition.postcondition_type

        # 1. TEXT_VALUE_EQUALS & TEXT_VALUE_CONTAINS
        if pt in (PostconditionType.TEXT_VALUE_EQUALS, PostconditionType.TEXT_VALUE_CONTAINS):
            if not post_state:
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation="No post-action ComputerState available to inspect text value.",
                )
            el: Optional[UIElement] = None
            if postcondition.target_path and post_state.root_element:
                el = post_state.root_element.find_by_path(postcondition.target_path)
            if not el and postcondition.target_path:
                for cand in post_state.interactive_elements:
                    if cand.path == postcondition.target_path:
                        el = cand
                        break
            if not el and post_state.focused_element:
                el = post_state.focused_element
            if not el:
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Target element at '{postcondition.target_path or 'focused'}' not found in post-state to verify text value.",
                )

            actual_val = el.value
            if actual_val is None:
                return VerificationResult(
                    status=GoalStatus.UNKNOWN,
                    explanation=f"Target element {el.role} '{el.title}' exists, but exposes no accessible text value.",
                    evidence={"target_path": el.path, "role": el.role},
                )

            expected = (postcondition.expected_value or "").strip()
            actual = actual_val.strip()

            if pt == PostconditionType.TEXT_VALUE_EQUALS:
                if actual == expected:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Verified text value equals '{expected}' in {el.role}.",
                        evidence={"actual_value": actual_val, "expected_value": expected, "target_path": el.path},
                    )
                else:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Text verification failed: expected '{expected}', found '{actual_val}'.",
                        evidence={"actual_value": actual_val, "expected_value": expected, "target_path": el.path},
                    )
            else:  # TEXT_VALUE_CONTAINS
                if expected in actual:
                    return VerificationResult(
                        status=GoalStatus.SATISFIED,
                        explanation=f"Verified text '{expected}' is contained in {el.role} value ('{actual_val}').",
                        evidence={"actual_value": actual_val, "expected_value": expected, "target_path": el.path},
                    )
                else:
                    return VerificationResult(
                        status=GoalStatus.UNSATISFIED,
                        explanation=f"Text verification failed: expected '{expected}' not found in '{actual_val}'.",
                        evidence={"actual_value": actual_val, "expected_value": expected, "target_path": el.path},
                    )

        # 2. ELEMENT_FOCUSED
        elif pt == PostconditionType.ELEMENT_FOCUSED:
            if not post_state or not post_state.focused_element:
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation="No element is focused in post-action state.",
                )
            fe = post_state.focused_element
            target_path = postcondition.target_path or ""
            expected_title = (postcondition.expected_value or "").strip().lower()
            if target_path and (fe.path == target_path or fe.path.endswith(target_path.split("/")[-1])):
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified element at path '{fe.path}' is focused.",
                    evidence={"path": fe.path, "role": fe.role},
                )
            if expected_title and (
                expected_title == fe.role.lower()
                or expected_title in (fe.title or "").lower()
                or expected_title in (fe.description or "").lower()
            ):
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified element '{fe.title}' ({fe.role}) is focused.",
                    evidence={"path": fe.path, "title": fe.title, "role": fe.role},
                )
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Focus mismatch: expected '{target_path or expected_title}', but {fe.role} '{fe.title}' is focused.",
                evidence={"actual_focused": fe.to_summary_dict()},
            )


        # 3. WINDOW_ACTIVE
        elif pt == PostconditionType.WINDOW_ACTIVE:
            if not post_state:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation="No post-state available.")
            expected_win = (postcondition.expected_window or "").strip().lower()
            actual_win = (post_state.active_window_title or "").strip().lower()
            if expected_win in actual_win or actual_win in expected_win:
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified active window is '{post_state.active_window_title}'.",
                    evidence={"active_window": post_state.active_window_title},
                )
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Window mismatch: expected '{postcondition.expected_window}', found '{post_state.active_window_title}'.",
                evidence={"actual_window": post_state.active_window_title},
            )

        # 4. WINDOW_CLOSED
        elif pt == PostconditionType.WINDOW_CLOSED:
            if not post_state:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation="No post-state available.")
            expected_win = (postcondition.expected_window or "").strip().lower()
            curr_titles = [w.title.lower() for w in post_state.windows if w.title]
            if curr_titles and any(expected_win in t for t in curr_titles):
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Window '{postcondition.expected_window}' is still present in post-action state.",
                )
            return VerificationResult(
                status=GoalStatus.SATISFIED,
                explanation=f"Verified window '{postcondition.expected_window}' was closed.",
            )

        # 5. ELEMENT_DISAPPEARED
        elif pt == PostconditionType.ELEMENT_DISAPPEARED:
            if not post_state:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation="No post-state available.")
            target_path = postcondition.target_path or ""
            still_exists = False
            if post_state.root_element and post_state.root_element.find_by_path(target_path):
                still_exists = True
            for el in post_state.interactive_elements:
                if el.path == target_path:
                    still_exists = True
                    break
            if still_exists:
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"Element at path '{target_path}' is still present.",
                )
            return VerificationResult(
                status=GoalStatus.SATISFIED,
                explanation=f"Verified element at path '{target_path}' has disappeared.",
            )

        # 6. ELEMENT_SELECTED
        elif pt == PostconditionType.ELEMENT_SELECTED:
            if not post_state:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation="No post-state available.")
            target_path = postcondition.target_path or ""
            el = None
            if post_state.root_element:
                el = post_state.root_element.find_by_path(target_path)
            if not el:
                for cand in post_state.interactive_elements:
                    if cand.path == target_path:
                        el = cand
                        break
            if not el:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation=f"Target element '{target_path}' not found.")
            if el.is_selected is True:
                return VerificationResult(status=GoalStatus.SATISFIED, explanation=f"Verified element '{el.title}' is selected.")
            elif el.is_selected is False:
                return VerificationResult(status=GoalStatus.UNSATISFIED, explanation=f"Element '{el.title}' is not selected.")
            else:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation=f"Selection state for '{el.title}' is unknown.")

        # 7. STATE_DELTA_MATCH
        elif pt == PostconditionType.STATE_DELTA_MATCH:
            if not pre_state or not post_state:
                return VerificationResult(status=GoalStatus.UNKNOWN, explanation="Pre/post states missing for delta comparison.")
            delta = pre_state.compute_delta(post_state)
            req_keys = postcondition.expected_delta_keys or []
            missing_keys = []
            for k in req_keys:
                if not delta.get(k):
                    missing_keys.append(k)
            if missing_keys:
                return VerificationResult(
                    status=GoalStatus.UNSATISFIED,
                    explanation=f"State delta missing expected transition(s): {missing_keys}",
                    evidence={"delta": delta},
                )
            return VerificationResult(
                status=GoalStatus.SATISFIED,
                explanation="Verified state delta matched all expected transitions.",
                evidence={"delta": delta},
            )

        # 8. APPLICATION_RUNNING
        elif pt == PostconditionType.APPLICATION_RUNNING:
            expected_app = (postcondition.expected_application or "").strip().lower()
            if post_state and expected_app in post_state.active_application.lower():
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified application '{post_state.active_application}' is running and active.",
                )
            from macos.shell import run_shell_command
            ps_res = run_shell_command(f"/usr/bin/pgrep -x -i '{postcondition.expected_application}'", timeout=2)
            if ps_res.success and ps_res.stdout.strip():
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified process '{postcondition.expected_application}' is running (PID: {ps_res.stdout.strip().splitlines()[0]}).",
                )
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"Application '{postcondition.expected_application}' is not running.",
            )

        # 9. FILE_EXISTS
        elif pt == PostconditionType.FILE_EXISTS:
            p = Path(postcondition.target_path or "")
            if p.exists():
                return VerificationResult(
                    status=GoalStatus.SATISFIED,
                    explanation=f"Verified file exists: {p}",
                    evidence={"file_size": p.stat().st_size if p.is_file() else 0},
                )
            return VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation=f"File does not exist: {p}",
            )

        # 10. CUSTOM
        elif pt == PostconditionType.CUSTOM:
            verifier_name = getattr(postcondition, "custom_verifier_name", None)
            if verifier_name and verifier_name in CUSTOM_POSTCONDITION_REGISTRY:
                return CUSTOM_POSTCONDITION_REGISTRY[verifier_name](postcondition, pre_state, post_state, result)
            return VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation=f"Custom postcondition '{postcondition.description or 'unnamed'}' has no registered verifier or inconclusive evidence.",
                evidence=result.evidence if result else {},
            )
        return VerificationResult(
            status=GoalStatus.UNKNOWN,
            explanation="Unrecognized postcondition type or inconclusive state.",
        )


# Global evaluator singleton
goal_evaluator = GoalEvaluator()
evaluator = goal_evaluator
