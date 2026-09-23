"""Phase 1.1 Verification Invariant Tests for MAX.

Proves the 14 core truthfulness invariants required by Phase 1.1:
- Test 1: Terminal execution exits 0, but requested postcondition (content) is false -> UNSATISFIED.
- Test 2: Terminal execution exits 0, but evaluator cannot determine postcondition -> UNKNOWN.
- Test 3: Delete an already-absent file -> NOT blindly SATISFIED (UNSATISFIED).
- Test 4: Delete an existing file, filesystem verifies disappearance -> SATISFIED.
- Test 5: Write file with correct content -> SATISFIED only after independent content verification.
- Test 6: Write file with wrong content -> UNSATISFIED.
- Test 7: Move file -> source absent, destination present -> SATISFIED.
- Test 8: Replanning history [failed, recovery, retry UNKNOWN] -> UNKNOWN (planner not told completed).
- Test 9: Recovery succeeds but original requirement remains failed -> UNSATISFIED.
- Test 10: Optional step fails while all mandatory steps are independently verified -> SATISFIED with limitation.
- Test 11: Mandatory step succeeds at execution level but verification is UNKNOWN -> UNKNOWN.
- Test 12: Compound goal: A = SATISFIED, B = UNKNOWN -> UNKNOWN.
- Test 13: Compound goal: A = SATISFIED, B = UNSATISFIED -> UNSATISFIED.
- Test 14: Compound goal: A = SATISFIED, B = UNSUPPORTED -> UNSUPPORTED.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent.core import AgentCore, StepExecutionRecord
from agent.observer import EnvironmentObservation
from agent.planner import Plan, PlanStep, PlannerStatus
from capabilities.base import ExecutionResult
from verification.base import GoalEvaluation, GoalStatus, VerificationResult
from verification.evaluator import GoalEvaluator, goal_evaluator


class TestPhase11Verification(unittest.TestCase):
    """Rigorous invariant tests for Phase 1.1 Truthful Execution."""

    def setUp(self):
        self.evaluator = GoalEvaluator()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="max_phase1_1_test_"))
        self.obs = EnvironmentObservation(
            current_directory=str(self.temp_dir),
            active_application="Finder",
        )

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # Test 1: Terminal exit 0, but requested postcondition is false -> UNSATISFIED
    # =========================================================================
    def test_1_terminal_success_but_postcondition_false_is_unsatisfied(self):
        """Test 1: Shell command exits 0, but requested file content is HELLO while actual is WRONG.

        Expected: UNSATISFIED (NOT SATISFIED).
        """
        target_file = self.temp_dir / "test1.txt"
        target_file.write_text("WRONG", encoding="utf-8")

        step = PlanStep(
            step_number=1,
            capability="terminal",
            action="execute_command",
            args={
                "command": f"touch {target_file}",
                "expected_file": str(target_file),
                "expected_content": "HELLO",
            },
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="terminal",
            action="execute_command",
            exit_code=0,
            data={"exit_code": 0, "stdout": ""},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs)
        self.assertNotEqual(
            v.status,
            GoalStatus.SATISFIED,
            "Terminal exit 0 with wrong postcondition content must NEVER be SATISFIED!",
        )
        self.assertEqual(v.status, GoalStatus.UNSATISFIED)
        self.assertIn("content mismatch", v.explanation.lower())

    # =========================================================================
    # Test 2: Terminal exit 0, but unprovable postcondition -> UNKNOWN
    # =========================================================================
    def test_2_terminal_success_but_unprovable_postcondition_is_unknown(self):
        """Test 2: Shell command exits 0, but action has no verifiable postcondition.

        Expected: UNKNOWN (NOT SATISFIED).
        """
        step = PlanStep(
            step_number=1,
            capability="terminal",
            action="execute_command",
            args={"command": "systemsetup -setusingnetworktime on"},
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="terminal",
            action="execute_command",
            exit_code=0,
            data={"exit_code": 0, "stdout": "Network Time: on"},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs)
        self.assertNotEqual(
            v.status,
            GoalStatus.SATISFIED,
            "Arbitrary state-modifying terminal command with unproven postcondition must NOT be SATISFIED!",
        )
        self.assertEqual(v.status, GoalStatus.UNKNOWN)
        self.assertIn("could not be independently verified", v.explanation)

    # =========================================================================
    # Test 3: Delete an already-absent file -> NOT blindly SATISFIED (UNSATISFIED)
    # =========================================================================
    def test_3_delete_already_absent_file_is_not_satisfied(self):
        """Test 3: Attempting to delete a file that was already absent prior to execution

        must NOT be blindly marked SATISFIED.
        """
        absent_path = self.temp_dir / "already_absent.txt"
        self.assertFalse(absent_path.exists())

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="move_to_trash",
            args={"path": str(absent_path)},
            is_optional=False,
        )
        # Pre-observation recorded that file was already absent
        pre_obs = EnvironmentObservation(
            current_directory=str(self.temp_dir),
            active_application="Finder",
            metadata={f"exists:{absent_path}": False},
        )
        res = ExecutionResult(
            success=True,  # e.g. a tool or mock claiming success
            capability="filesystem",
            action="move_to_trash",
            data={"path": str(absent_path), "already_absent": True},
            evidence={"already_absent": True, "path": str(absent_path)},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs, pre_observation=pre_obs)
        self.assertNotEqual(
            v.status,
            GoalStatus.SATISFIED,
            "Deleting an already absent file must NOT be marked SATISFIED!",
        )
        self.assertEqual(v.status, GoalStatus.UNSATISFIED)
        self.assertIn("already absent", v.explanation.lower())

    # =========================================================================
    # Test 4: Delete an existing file -> SATISFIED when confirmed gone
    # =========================================================================
    def test_4_delete_existing_file_verified_disappears_is_satisfied(self):
        """Test 4: Delete an existing file where pre-state had file and post-state has it gone.

        Expected: SATISFIED.
        """
        target = self.temp_dir / "to_delete.txt"
        # Simulate transition: file existed before, was removed during execution
        pre_obs = EnvironmentObservation(
            current_directory=str(self.temp_dir),
            active_application="Finder",
            metadata={f"exists:{target}": True},
        )
        self.assertFalse(target.exists())  # Now absent after deletion

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="move_to_trash",
            args={"path": str(target)},
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="filesystem",
            action="move_to_trash",
            data={"path": str(target), "removed": True},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs, pre_observation=pre_obs)
        self.assertEqual(v.status, GoalStatus.SATISFIED)
        self.assertIn("verified removed", v.explanation.lower())

    # =========================================================================
    # Test 5: Write file with correct content -> SATISFIED
    # =========================================================================
    def test_5_write_file_correct_content_is_satisfied(self):
        """Test 5: Write file where content on disk matches requested content.

        Expected: SATISFIED only after independent content verification.
        """
        target = self.temp_dir / "file5.txt"
        expected = "Exact expected payload 12345"
        target.write_text(expected, encoding="utf-8")

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": str(target), "content": expected},
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="filesystem",
            action="write_file",
            data={"path": str(target), "bytes_written": len(expected)},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs)
        self.assertEqual(v.status, GoalStatus.SATISFIED)
        self.assertTrue(v.evidence.get("content_verified"))

    # =========================================================================
    # Test 6: Write file with wrong content -> UNSATISFIED
    # =========================================================================
    def test_6_write_file_wrong_content_is_unsatisfied(self):
        """Test 6: Write file exists on disk, but content does not match expected content.

        Expected: UNSATISFIED (NOT SATISFIED).
        """
        target = self.temp_dir / "file6.txt"
        target.write_text("Corrupted or unexpected content", encoding="utf-8")

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": str(target), "content": "Desired content"},
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="filesystem",
            action="write_file",
            data={"path": str(target)},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs)
        self.assertEqual(v.status, GoalStatus.UNSATISFIED)
        self.assertIn("content mismatch", v.explanation.lower())

    # =========================================================================
    # Test 7: Move file -> source absent, destination present -> SATISFIED
    # =========================================================================
    def test_7_move_file_source_absent_destination_present_is_satisfied(self):
        """Test 7: Move file verifies that source path is absent and destination path exists.

        Expected: SATISFIED.
        """
        src = self.temp_dir / "source.txt"
        dst = self.temp_dir / "destination.txt"
        # Simulate completed move: dst exists, src absent
        dst.write_text("Moved content", encoding="utf-8")
        self.assertFalse(src.exists())
        self.assertTrue(dst.exists())

        pre_obs = EnvironmentObservation(
            current_directory=str(self.temp_dir),
            active_application="Finder",
            metadata={f"exists:{src}": True},
        )

        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="move_file",
            args={"source": str(src), "destination": str(dst)},
            is_optional=False,
        )
        res = ExecutionResult(
            success=True,
            capability="filesystem",
            action="move_file",
            data={"source": str(src), "destination": str(dst)},
        )

        v = self.evaluator.evaluate_step(step, res, self.obs, pre_observation=pre_obs)
        self.assertEqual(v.status, GoalStatus.SATISFIED)
        self.assertTrue(v.evidence.get("source_gone"))
        self.assertTrue(v.evidence.get("destination_exists"))

    # =========================================================================
    # Test 8: Replanning history [failed, recovery, retry UNKNOWN] -> UNKNOWN
    # =========================================================================
    def test_8_replanning_history_labels_failed_and_unknown_correctly(self):
        """Test 8: Sequence [step A = FAILED, recovery = SATISFIED, retry A = UNKNOWN].

        Goal evaluation must report UNKNOWN, and the planner must NOT be told step A completed.
        """
        step_a = PlanStep(
            step_number=1,
            capability="applications",
            action="activate_application",
            args={"application_name": "Terminal"},
            is_optional=False,
        )
        rec_failed = StepExecutionRecord(
            step=step_a,
            result=ExecutionResult(success=False, capability="applications", action="activate_application", error="Timeout"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Activation failed."),
        )

        step_recov = PlanStep(
            step_number=2,
            capability="applications",
            action="list_installed_applications",
            args={},
            is_optional=False,
            is_recovery=True,
        )
        rec_recov = StepExecutionRecord(
            step=step_recov,
            result=ExecutionResult(success=True, capability="applications", action="list_installed_applications"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Listed applications."),
        )

        step_retry = PlanStep(
            step_number=1,
            capability="applications",
            action="activate_application",
            args={"application_name": "Terminal"},
            is_optional=False,
        )
        rec_retry = StepExecutionRecord(
            step=step_retry,
            result=ExecutionResult(success=True, capability="applications", action="activate_application"),
            verification=VerificationResult(status=GoalStatus.UNKNOWN, explanation="Window focus ambiguous."),
        )

        records = [rec_failed, rec_recov, rec_retry]
        goal_eval = self.evaluator.evaluate_goal(
            user_request="Activate Terminal",
            steps_executed=records,
            remaining_steps=[],
            last_observation=self.obs,
        )

        self.assertEqual(
            goal_eval.status,
            GoalStatus.UNKNOWN,
            "Sequence with retry ending in UNKNOWN must evaluate overall goal to UNKNOWN!",
        )

        # Check replanning prompt categorization logic: step A must NOT be in verified_completed_steps
        verified_completed = [
            f"{r.step.capability}.{r.step.action}"
            for r in records
            if r.verification.status == GoalStatus.SATISFIED and not getattr(r.step, "is_recovery", False)
        ]
        self.assertNotIn(
            "applications.activate_application",
            verified_completed,
            "Failed/unverified step A must NEVER be reported as completed successfully to the planner!",
        )

    # =========================================================================
    # Test 9: Recovery succeeds but original requirement remains failed -> UNSATISFIED
    # =========================================================================
    def test_9_recovery_succeeds_but_original_mandatory_remains_unsatisfied(self):
        """Test 9: Recovery step succeeds, but original mandatory step was not retried/satisfied.

        Expected: UNSATISFIED.
        """
        step1 = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": "/tmp/nonexistent_perm_denied.txt", "content": "foo"},
            is_optional=False,
        )
        rec1 = StepExecutionRecord(
            step=step1,
            result=ExecutionResult(success=False, capability="filesystem", action="write_file", error="Permission denied"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Write failed."),
        )

        step_recov = PlanStep(
            step_number=2,
            capability="terminal",
            action="execute_command",
            args={"command": "whoami"},
            is_optional=False,
            is_recovery=True,
        )
        rec_recov = StepExecutionRecord(
            step=step_recov,
            result=ExecutionResult(success=True, capability="terminal", action="execute_command", exit_code=0),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="whoami executed."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Write file",
            steps_executed=[rec1, rec_recov],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNSATISFIED)

    # =========================================================================
    # Test 10: Optional step fails while all mandatory steps verified -> SATISFIED with limitation
    # =========================================================================
    def test_10_optional_step_fails_mandatory_verified_is_satisfied_with_limitation(self):
        """Test 10: Mandatory step is verified SATISFIED, optional step fails.

        Expected: Goal SATISFIED, but failure recorded in limitations.
        """
        step_mandatory = PlanStep(
            step_number=1,
            capability="filesystem",
            action="read_file",
            args={"path": "/tmp/sample.txt"},
            is_optional=False,
        )
        rec_mandatory = StepExecutionRecord(
            step=step_mandatory,
            result=ExecutionResult(success=True, capability="filesystem", action="read_file"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="File read."),
        )

        step_optional = PlanStep(
            step_number=2,
            capability="macos",
            action="show_notification",
            args={"message": "Done"},
            is_optional=True,
        )
        rec_optional = StepExecutionRecord(
            step=step_optional,
            result=ExecutionResult(success=False, capability="macos", action="show_notification", error="Notification error"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Notification failed."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Read file and notify",
            steps_executed=[rec_mandatory, rec_optional],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(
            goal_eval.status,
            GoalStatus.SATISFIED,
            "Optional failure must NOT invalidate overall verified mandatory goal.",
        )

    # =========================================================================
    # Test 11: Mandatory step execution success but verification UNKNOWN -> UNKNOWN
    # =========================================================================
    def test_11_mandatory_step_execution_success_verification_unknown_is_unknown(self):
        """Test 11: Tool returned success=True, but independent verification produced UNKNOWN.

        Expected: UNKNOWN (never SATISFIED).
        """
        step = PlanStep(
            step_number=1,
            capability="browser",
            action="open_url",
            args={"url": "https://example.com"},
            is_optional=False,
        )
        rec = StepExecutionRecord(
            step=step,
            result=ExecutionResult(success=True, capability="browser", action="open_url"),
            verification=VerificationResult(status=GoalStatus.UNKNOWN, explanation="No tab verification available."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Open example.com",
            steps_executed=[rec],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNKNOWN)

    # =========================================================================
    # Test 12: Compound goal: A = SATISFIED, B = UNKNOWN -> UNKNOWN
    # =========================================================================
    def test_12_compound_goal_satisfied_and_unknown_is_unknown(self):
        """Test 12: Mandatory steps [SATISFIED, UNKNOWN].

        Expected: UNKNOWN.
        """
        step_a = PlanStep(step_number=1, capability="filesystem", action="read_file", args={}, is_optional=False)
        rec_a = StepExecutionRecord(
            step=step_a,
            result=ExecutionResult(success=True, capability="filesystem", action="read_file"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Read ok."),
        )

        step_b = PlanStep(step_number=2, capability="browser", action="open_url", args={}, is_optional=False)
        rec_b = StepExecutionRecord(
            step=step_b,
            result=ExecutionResult(success=True, capability="browser", action="open_url"),
            verification=VerificationResult(status=GoalStatus.UNKNOWN, explanation="Unverifiable browser tab."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Read file and open browser",
            steps_executed=[rec_a, rec_b],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNKNOWN)

    # =========================================================================
    # Test 13: Compound goal: A = SATISFIED, B = UNSATISFIED -> UNSATISFIED
    # =========================================================================
    def test_13_compound_goal_satisfied_and_unsatisfied_is_unsatisfied(self):
        """Test 13: Mandatory steps [SATISFIED, UNSATISFIED].

        Expected: UNSATISFIED.
        """
        step_a = PlanStep(step_number=1, capability="filesystem", action="read_file", args={}, is_optional=False)
        rec_a = StepExecutionRecord(
            step=step_a,
            result=ExecutionResult(success=True, capability="filesystem", action="read_file"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Read ok."),
        )

        step_b = PlanStep(step_number=2, capability="filesystem", action="write_file", args={}, is_optional=False)
        rec_b = StepExecutionRecord(
            step=step_b,
            result=ExecutionResult(success=False, capability="filesystem", action="write_file"),
            verification=VerificationResult(status=GoalStatus.UNSATISFIED, explanation="Write failed."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Read and write file",
            steps_executed=[rec_a, rec_b],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNSATISFIED)

    # =========================================================================
    # Test 14: Compound goal: A = SATISFIED, B = UNSUPPORTED -> UNSUPPORTED
    # =========================================================================
    def test_14_compound_goal_satisfied_and_unsupported_is_unsupported(self):
        """Test 14: Mandatory steps [SATISFIED, UNSUPPORTED].

        Expected: UNSUPPORTED.
        """
        step_a = PlanStep(step_number=1, capability="filesystem", action="read_file", args={}, is_optional=False)
        rec_a = StepExecutionRecord(
            step=step_a,
            result=ExecutionResult(success=True, capability="filesystem", action="read_file"),
            verification=VerificationResult(status=GoalStatus.SATISFIED, explanation="Read ok."),
        )

        step_b = PlanStep(step_number=2, capability="hardware", action="overclock_gpu", args={}, is_optional=False)
        rec_b = StepExecutionRecord(
            step=step_b,
            result=ExecutionResult(success=False, capability="hardware", action="overclock_gpu", error="Unsupported"),
            verification=VerificationResult(status=GoalStatus.UNSUPPORTED, explanation="Hardware feature unsupported."),
        )

        goal_eval = self.evaluator.evaluate_goal(
            user_request="Read file and overclock GPU",
            steps_executed=[rec_a, rec_b],
            remaining_steps=[],
            last_observation=self.obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
