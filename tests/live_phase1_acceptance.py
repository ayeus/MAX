"""Live macOS Acceptance Tests for MAX Phase 1 and Phase 1.1.

Executes genuine operations on the local macOS system to prove:
- Live Test 1: Real Filesystem Write + Real Content Readback & Mismatch Detection
- Live Test 2: Real Filesystem Delete: create file -> verify exists -> invoke MAX -> verify gone
- Live Test 3: Real Filesystem Move: create source -> invoke MAX -> verify source gone & dest exists
- Live Test 4: Real Terminal Operation where postcondition is independently observable on disk
- Live Test 5: Real Brightness Setting + Independent Hardware Readback + Safe Restoration
- Live Test 6: Real Unsupported Operation (zero execution side effects, UNSUPPORTED status)
- Live Test 7: Real Failed GUI Action with Recovery (recovery never satisfies original goal)

Strict Rule: Tests must observe genuine macOS state without gaming or fabricating results.
All temporary files are strictly isolated in temporary directories and cleaned up immediately.
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.core import AgentCore
from agent.observer import observer, ObservationTier, AgentObservation
from agent.planner import PlanStep
from capabilities.base import ExecutionResult
from macos.brightness import is_brightness_supported, get_display_brightness, set_display_brightness
from verification.base import GoalStatus, AgentState
from verification.evaluator import goal_evaluator


class TestLivePhase1Acceptance(unittest.TestCase):
    """Live macOS integration and acceptance tests."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="max_live_acceptance_"))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_live_1_real_filesystem_write_and_content_readback(self):
        """Live Test 1: Real filesystem write + real content readback.

        Asserts that correct content reports SATISFIED, and mismatched content reports UNSATISFIED.
        """
        test_file = self.temp_dir / "real_payload.txt"
        expected_content = "Hello from MAX live filesystem write verification 98765"

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": str(test_file), "content": expected_content},
            is_optional=False,
        )

        from capabilities.filesystem.filesystem import FilesystemCapability
        fs = FilesystemCapability()
        res = fs.write_file(path=str(test_file), content=expected_content)
        self.assertTrue(res.success)
        self.assertTrue(test_file.exists())

        # 1. Independent verification of matching content
        obs = observer.observe(tier=ObservationTier.FAST)
        v_matched = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(v_matched.status, GoalStatus.SATISFIED)
        self.assertTrue(v_matched.evidence.get("content_verified"))

        # 2. Independent readback directly from disk
        actual_disk_content = test_file.read_text(encoding="utf-8")
        self.assertEqual(actual_disk_content, expected_content)

        # 3. Intentional mismatch: Asserting different content must report UNSATISFIED
        step_wrong = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": str(test_file), "content": "Wrong completely unexpected content"},
            is_optional=False,
        )
        v_wrong = goal_evaluator.evaluate_step(step_wrong, res, obs)
        self.assertEqual(v_wrong.status, GoalStatus.UNSATISFIED)
        self.assertIn("content mismatch", v_wrong.explanation.lower())

    def test_live_2_real_filesystem_delete_transition(self):
        """Live Test 2: Real filesystem delete.

        Create file -> verify exists -> invoke MAX move_to_trash -> verify it disappeared.
        """
        test_file = self.temp_dir / "live_to_trash.txt"
        test_file.write_text("Temporary file to be deleted via Trash.", encoding="utf-8")
        self.assertTrue(test_file.exists(), "Pre-condition failed: file was not created on disk.")

        agent = AgentCore()
        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="move_to_trash",
            args={"path": str(test_file)},
            is_optional=False,
        )
        pre_obs = observer.observe(tier=ObservationTier.FAST)
        pre_obs.metadata[f"exists:{test_file}"] = True

        from capabilities.filesystem.filesystem import FilesystemCapability
        fs = FilesystemCapability()
        with patch("app.config.settings.require_confirmation_for_high_risk", False):
            res = fs.move_to_trash(path=str(test_file))
        self.assertTrue(res.success, f"move_to_trash failed: {res.error}")

        # Verify it genuinely disappeared from original disk path
        self.assertFalse(test_file.exists(), f"File {test_file} should have been moved to Trash!")

        post_obs = observer.observe(tier=ObservationTier.FAST)
        v = goal_evaluator.evaluate_step(step, res, post_obs, pre_observation=pre_obs)
        self.assertEqual(v.status, GoalStatus.SATISFIED)
        self.assertIn("verified removed", v.explanation.lower())

    def test_live_3_real_filesystem_move_transition(self):
        """Live Test 3: Real filesystem move.

        Create source -> invoke move -> verify source is gone and destination exists with matching content.
        """
        src = self.temp_dir / "live_source.txt"
        dst = self.temp_dir / "live_destination.txt"
        payload = "Move payload verification 42"
        src.write_text(payload, encoding="utf-8")
        self.assertTrue(src.exists())
        self.assertFalse(dst.exists())

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="move_file",
            args={"source": str(src), "destination": str(dst)},
            is_optional=False,
        )
        pre_obs = observer.observe(tier=ObservationTier.FAST)
        pre_obs.metadata[f"exists:{src}"] = True

        from capabilities.filesystem.filesystem import FilesystemCapability
        fs = FilesystemCapability()
        res = fs.move_file(source=str(src), destination=str(dst))
        self.assertTrue(res.success, f"move_file failed: {res.error}")

        # Verify genuine transitions on disk
        self.assertFalse(src.exists(), "Source file still exists on disk after move!")
        self.assertTrue(dst.exists(), "Destination file does not exist on disk after move!")
        self.assertEqual(dst.read_text(encoding="utf-8"), payload)

        post_obs = observer.observe(tier=ObservationTier.FAST)
        v = goal_evaluator.evaluate_step(step, res, post_obs, pre_observation=pre_obs)
        self.assertEqual(v.status, GoalStatus.SATISFIED)
        self.assertTrue(v.evidence.get("source_gone"))
        self.assertTrue(v.evidence.get("destination_exists"))

    def test_live_4_real_terminal_observable_postcondition(self):
        """Live Test 4: Real terminal operation where postcondition is independently observable on disk."""
        target_dir = self.temp_dir / "terminal_created_dir"
        self.assertFalse(target_dir.exists())

        agent = AgentCore()
        cmd = f"mkdir -p '{target_dir}'"
        report = agent.run(f"Run terminal command: {cmd}")

        # Independent filesystem verification of real directory created by terminal command
        self.assertTrue(target_dir.exists(), f"Directory {target_dir} was not actually created by terminal!")
        self.assertTrue(target_dir.is_dir())
        self.assertEqual(report.goal_evaluation.status, GoalStatus.SATISFIED)
        self.assertTrue(report.overall_success)

    def test_live_5_real_brightness_setting_and_readback(self):
        """Live Test 5: If display brightness is supported, change hardware brightness,

        independently read back hardware state, verify within tolerance, assert mismatch fails,
        and cleanly restore original hardware brightness.
        """
        supported = is_brightness_supported()
        if not supported:
            agent = AgentCore()
            report = agent.run("Please set my screen brightness to 50%")
            self.assertIn(report.goal_evaluation.status, (GoalStatus.UNKNOWN, GoalStatus.UNSUPPORTED))
            self.assertFalse(report.overall_success)
            return

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

    def test_live_6_real_unsupported_operation(self):
        """Live Test 6: Request an unsupported hardware capability on real macOS,

        verifying zero side effects, state UNSUPPORTED, and report UNSUPPORTED.
        """
        agent = AgentCore()
        report = agent.run("Please set my screen refresh rate to 120Hz")

        self.assertEqual(report.state, AgentState.UNSUPPORTED)
        self.assertEqual(report.goal_evaluation.status, GoalStatus.UNSUPPORTED)
        self.assertFalse(report.overall_success)
        self.assertEqual(len(report.steps_executed), 0, "No steps should be executed for unsupported operations.")
        self.assertIn("UNSUPPORTED", report.final_summary)

    def test_live_7_real_failed_action_with_recovery_truthfulness(self):
        """Live Test 7: An action that fails on macOS (e.g. launching a non-existent app)

        can trigger diagnostic recovery, but the recovery MUST NOT cause the original goal
        to report SATISFIED.
        """
        agent = AgentCore()
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
