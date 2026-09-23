"""Phase 15, 16, 17, 29: Genuine Autonomous AgentCore Live Replanning Test on macOS.

This test MUST invoke AgentCore as the actual orchestrator.
The test harness only:
  1. Prepares the initial macOS application state.
  2. Spawns an external disturbance thread on the real desktop (e.g. switches active app to Finder).
  3. Calls agent.execute_goal(goal).
  4. Collects and validates evidence from the AgentExecutionReport and ComputerUseTrace.
  5. Cleans up windows.

Zero manual recovery calls in the test harness.
AgentCore itself MUST perform:
  observe -> act -> detect real divergence -> fail verification -> replan ->
  generate recovery -> execute recovery -> fresh observe -> re-ground -> retry -> verify -> SATISFIED.
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from capabilities import initialize_default_capabilities
from capabilities.accessibility.accessibility import run_applescript
from capabilities.accessibility.tree import tree_extractor
from capabilities.accessibility.models import TargetValidity
from agent.core import AgentCore, AgentExecutionReport
from agent.goal import Goal, Subgoal, ActionIntent, ActionType, SubgoalStatus
from verification.base import PostconditionType, ExpectedPostcondition, GoalStatus


def run_live_agentcore_replanning_test() -> dict[str, Any]:
    """Execute autonomous AgentCore live replanning cycle and record forensic evidence."""
    print("\n=======================================================")
    print("PHASE 15/29: RUNNING AUTONOMOUS AGENTCORE REPLANNING TEST")
    print("=======================================================\n")

    if sys.platform != "darwin":
        raise RuntimeError("Live macOS replanning test requires Darwin environment.")

    initialize_default_capabilities()
    cycle_start = time.perf_counter()

    # Step 1: Prepare real TextEdit document on macOS
    print("[1/5] Preparing clean TextEdit document...")
    setup_script = '''
    tell application "TextEdit"
        activate
        close every document saving no
        make new document
    end tell
    tell application "System Events" to tell process "TextEdit"
        repeat 20 times
            if (count of windows) > 0 then exit repeat
            delay 0.1
        end repeat
    end tell
    '''
    run_applescript(setup_script)
    time.sleep(0.5)

    tree_extractor.invalidate_cache()
    init_state = tree_extractor.get_computer_state(application_name="TextEdit", force_refresh=True)
    if not init_state or init_state.active_application != "TextEdit":
        raise RuntimeError(f"TextEdit setup failed; active application is '{init_state.active_application if init_state else None}'.")

    # Step 2: Define Goal with Subgoal requiring text entry into TextEdit
    test_token = f"AgentCore_Replanned_{int(time.time())}"
    print(f"[2/5] Formulating Goal with unique token: '{test_token}'...")

    typing_subgoal = Subgoal(
        description="Type unique test token into document editor",
        target_description="TextEdit document text area",
        target_constraints={"role": "text_area", "application": "TextEdit"},
        action_intent=ActionIntent(
            action_type=ActionType.TYPE_TEXT,
            parameters={
                "text": test_token,
                "clear_first": True,
                "press_return": False,
                "application_name": "TextEdit",
            },
        ),
        expected_postcondition=ExpectedPostcondition(
            postcondition_type=PostconditionType.TEXT_VALUE_CONTAINS,
            expected_value=test_token,
            expected_application="TextEdit",
        ),
        max_attempts=3,
    )
    goal = Goal(objective=f"Write '{test_token}' into TextEdit", subgoals=[typing_subgoal])

    # Step 3: Set up real desktop external disturbance thread
    # Disturbance switches active application to Finder during Subgoal 1 execution
    print("[3/5] Starting external disturbance thread to induce real desktop divergence...")
    disturbance_occurred = threading.Event()

    def induce_desktop_disturbance():
        # Wait until AgentCore begins subgoal execution
        time.sleep(0.35)
        print("  ⚡ [External Disturbance] Activating Finder via System Events...")
        run_applescript('tell application "Finder" to activate')
        disturbance_occurred.set()

    dist_thread = threading.Thread(target=induce_desktop_disturbance, daemon=True)
    dist_thread.start()

    # Step 4: Execute Goal AUTONOMOUSLY via AgentCore
    print("[4/5] Executing Goal via AgentCore.execute_goal()...")
    agent = AgentCore()
    report: AgentExecutionReport = agent.execute_goal(goal)
    dist_thread.join(timeout=2.0)

    total_latency_ms = (time.perf_counter() - cycle_start) * 1000.0

    # Step 5: Collect Evidence from Report and Trace
    print(f"[5/5] Analyzing execution evidence (Report status: {report.state.value})...")

    trace = report.trace
    trace_items = trace.items if trace else []
    steps_executed = report.steps_executed

    # Evidence extraction
    steps_count = len(steps_executed)
    has_failed_step = any(s.verification.status != GoalStatus.SATISFIED for s in steps_executed)
    has_recovery_subgoal = any(
        "re-activate" in s.step.action.lower() or "activate_application" in s.step.action.lower() or "activate" in str(s.step.args)
        for s in steps_executed
    )
    final_step_satisfied = (
        len(steps_executed) > 0 and steps_executed[-1].verification.status == GoalStatus.SATISFIED
    )
    overall_satisfied = (
        report.overall_success is True and report.goal_evaluation.status == GoalStatus.SATISFIED
    )

    # Phase 16: Snapshot & Target Tracking
    grounding_methods_observed = []
    for item in trace_items:
        grounding_methods_observed.append(item.grounding_method)

    # Verify TextEdit contains final token via independent observation
    tree_extractor.invalidate_cache()
    final_cs = tree_extractor.get_computer_state(application_name="TextEdit", force_refresh=True)
    final_text_verified = False
    actual_editor_text = ""
    if final_cs:
        target_el = None
        for cand in final_cs.interactive_elements:
            if cand.role in ("AXTextArea", "AXTextField"):
                target_el = cand
                break
        if not target_el and final_cs.focused_element:
            target_el = final_cs.focused_element
        if target_el and target_el.value:
            actual_editor_text = target_el.value
            final_text_verified = test_token in actual_editor_text

    # Cleanup: close TextEdit documents
    run_applescript('tell application "TextEdit" to close every document saving no')

    passed = (
        overall_satisfied
        and disturbance_occurred.is_set()
        and steps_count >= 2
        and has_recovery_subgoal
        and final_step_satisfied
        and final_text_verified
    )

    result_summary = {
        "test": "autonomous_agentcore_live_replanning",
        "type": "REAL MACOS",
        "objective": goal.objective,
        "token": test_token,
        "disturbance_induced": "Switched active application to Finder on live macOS desktop",
        "disturbance_occurred": disturbance_occurred.is_set(),
        "total_steps_executed_by_agentcore": steps_count,
        "agentcore_replanned": has_recovery_subgoal,
        "grounding_methods": grounding_methods_observed,
        "final_text_in_editor": actual_editor_text,
        "final_text_verified": final_text_verified,
        "overall_status": report.state.value,
        "overall_success": report.overall_success,
        "goal_evaluation_status": report.goal_evaluation.status.value,
        "goal_evaluation_explanation": report.goal_evaluation.explanation,
        "total_cycle_latency_ms": round(total_latency_ms, 2),
        "steps_summary": [
            {
                "step": s.step.step_number,
                "action": s.step.action,
                "args": s.step.args,
                "success": s.result.success,
                "verification_status": s.verification.status.value,
                "verification_explanation": s.verification.explanation,
            }
            for s in steps_executed
        ],
        "passed": passed,
    }

    print("\n-------------------------------------------------------")
    print(f"Autonomous Replanning Result: {'PASS' if passed else 'FAIL'} ({total_latency_ms:.2f} ms)")
    print(f"Total Steps Executed: {steps_count}")
    print(f"Final Verification: {report.goal_evaluation.status.value} (Verified Text: '{actual_editor_text.strip()}')")
    print("-------------------------------------------------------\n")

    return result_summary


if __name__ == "__main__":
    res = run_live_agentcore_replanning_test()
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/live_agentcore_replanning_report.json", "w") as f:
        json.dump(res, f, indent=2)
    sys.exit(0 if res["passed"] else 1)
