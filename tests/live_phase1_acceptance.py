"""Live macOS Acceptance Tests for MAX Phase 1.

Executes genuine operations on the local macOS system to prove:
- Live Test 1: Real Directory Creation + Independent Verification + Intentional Mismatch
- Live Test 2: Real Brightness Setting + Independent Hardware Readback + Safe Restoration
- Live Test 3: Real Unsupported Operation (zero execution side effects, UNSUPPORTED status)
- Live Test 4: Real Failed GUI Action with Recovery (recovery never satisfies original goal)

Strict Rule: Tests must observe genuine macOS state without gaming or fabricating results.
"""

import os
import shutil
import time
import unittest
from pathlib import Path

from agent.core import AgentCore
from agent.planner import PlanStep
from agent.observer import observer, ObservationTier, AgentObservation
from verification.base import GoalStatus, AgentState
from verification.evaluator import goal_evaluator
from capabilities.base import ExecutionResult
from macos.brightness import is_brightness_supported, get_display_brightness, set_display_brightness


class TestLivePhase1Acceptance(unittest.TestCase):
    """Live macOS integration and acceptance tests."""

    def test_live_1_real_directory_creation_and_mismatch(self):
        """Live Test 1: Create a real directory on disk via MAX, independently verify existence,

        and prove that asserting an uncreated file reports UNSATISFIED (no false success).
        """
        ts = int(time.time() * 1000)
        test_dir = Path(f"/tmp/max_phase1_live_{ts}")

        try:
            agent = AgentCore()
            cmd = f"mkdir -p {test_dir}"
            report = agent.run(f"Run terminal command: {cmd}")

            # 1. Independent filesystem verification of directory creation
            self.assertTrue(test_dir.exists(), f"Directory {test_dir} was not actually created on disk!")
            self.assertTrue(test_dir.is_dir())
            self.assertEqual(report.goal_evaluation.status, GoalStatus.SATISFIED)
            self.assertTrue(report.overall_success)

            # 2. Intentional verification mismatch: Assert an uncreated file exists inside the directory
            step_ghost_file = PlanStep(
                step_number=2,
                capability="filesystem",
                action="write_file",
                args={"path": str(test_dir / "ghost_file.txt"), "content": "nonexistent"},
            )
            # Evaluate against real filesystem
            obs = observer.observe(tier=ObservationTier.FAST)
            res_ghost = ExecutionResult(success=True, capability="filesystem", action="write_file")
            v_ghost = goal_evaluator.evaluate_step(step_ghost_file, res_ghost, obs)

            self.assertEqual(
                v_ghost.status,
                GoalStatus.UNSATISFIED,
                "Independent verification must report UNSATISFIED when file was not actually written to disk!",
            )
            self.assertIn("was not found on disk", v_ghost.explanation)

        finally:
            # Clean up test directory
            if test_dir.exists():
                shutil.rmtree(test_dir, ignore_errors=True)

    def test_live_2_real_brightness_setting_and_readback(self):
        """Live Test 2: If display brightness is supported, change hardware brightness,

        independently read back hardware state, verify within tolerance, assert mismatch fails,
        and cleanly restore original hardware brightness.
        """
        supported = is_brightness_supported()
        if not supported:
            # If hardware brightness is unsupported on this specific screen,
            # verify that setting brightness truthfully reports UNKNOWN or UNSUPPORTED, never SATISFIED.
            agent = AgentCore()
            report = agent.run("Please set my screen brightness to 50%")
            self.assertIn(report.goal_evaluation.status, (GoalStatus.UNKNOWN, GoalStatus.UNSUPPORTED))
            self.assertFalse(report.overall_success)
            return

        # Hardware brightness is supported
        ok_initial, initial_brightness, _ = get_display_brightness()
        self.assertTrue(ok_initial, "Failed to read initial hardware brightness via DisplayServices")
        self.assertIsNotNone(initial_brightness)

        # Pick a target within the display's 1:1 linear hardware range
        target_brightness = round(0.30 if initial_brightness < 0.25 else 0.20, 2)

        try:
            agent = AgentCore()
            target_pct = int(target_brightness * 100)
            report = agent.run(f"Set screen brightness to {target_pct}%")

            # Read back real hardware brightness independently
            ok_after, actual_brightness, _ = get_display_brightness()
            self.assertTrue(ok_after)
            self.assertAlmostEqual(actual_brightness, target_brightness, delta=0.08)

            # Verification in report must be SATISFIED
            self.assertEqual(report.goal_evaluation.status, GoalStatus.SATISFIED)
            self.assertTrue(report.overall_success)

            # Intentional verification mismatch: verify against an incorrect target (0.01)
            step_mismatch = PlanStep(
                step_number=1,
                capability="macos",
                action="set_brightness",
                args={"level": 0.01},
            )
            obs = observer.observe(tier=ObservationTier.FAST)
            res_mismatch = ExecutionResult(
                success=True,
                capability="macos",
                action="set_brightness",
                evidence={"before": initial_brightness, "after": actual_brightness, "target": 0.01},
            )
            v_mismatch = goal_evaluator.evaluate_step(step_mismatch, res_mismatch, obs)
            self.assertEqual(
                v_mismatch.status,
                GoalStatus.UNSATISFIED,
                f"Asserting brightness 0.01 when actual is {actual_brightness:.2f} must report UNSATISFIED!",
            )

        finally:
            # Cleanly restore original hardware brightness
            set_display_brightness(initial_brightness)
            _, restored, _ = get_display_brightness()
            self.assertAlmostEqual(restored, initial_brightness, delta=0.08)

    def test_live_3_real_unsupported_operation(self):
        """Live Test 3: Request an unsupported hardware capability on real macOS,

        verifying zero side effects, state UNSUPPORTED, and report UNSUPPORTED.
        """
        agent = AgentCore()
        report = agent.run("Please set my screen refresh rate to 120Hz")

        self.assertEqual(report.state, AgentState.UNSUPPORTED)
        self.assertEqual(report.goal_evaluation.status, GoalStatus.UNSUPPORTED)
        self.assertFalse(report.overall_success)
        self.assertEqual(len(report.steps_executed), 0, "No steps should be executed for unsupported operations.")
        self.assertIn("UNSUPPORTED", report.final_summary)

    def test_live_4_real_failed_action_with_recovery_truthfulness(self):
        """Live Test 4: An action that fails on macOS (e.g. launching a non-existent app)

        can trigger diagnostic recovery, but the recovery MUST NOT cause the original goal
        to report SATISFIED.
        """
        agent = AgentCore()
        # Non-existent app bundle
        report = agent.run("Open NonExistentApplication12345XYZ")

        self.assertNotEqual(
            report.goal_evaluation.status,
            GoalStatus.SATISFIED,
            "Failed app launch must NEVER report SATISFIED, regardless of recovery steps!",
        )
        self.assertEqual(report.state, AgentState.FAILED)
        self.assertFalse(report.overall_success)


if __name__ == "__main__":
    unittest.main()
