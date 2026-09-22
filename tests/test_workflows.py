"""Unit tests for Workflow management."""

import unittest
import tempfile
from pathlib import Path
from memory.workflows import WorkflowManager


class TestWorkflows(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.mgr = WorkflowManager(workflows_dir=Path(self.tmp_dir.name))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_save_and_get_workflow(self):
        saved = self.mgr.save_workflow(
            name="test_build_pipeline",
            description="Run build and tests",
            steps=[
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'build'"}},
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'test'"}},
            ],
        )
        self.assertTrue(saved)

        wf = self.mgr.get_workflow("test_build_pipeline")
        self.assertIsNotNone(wf)
        self.assertEqual(wf.name, "test_build_pipeline")
        self.assertEqual(len(wf.steps), 2)
        self.assertEqual(wf.steps[0].args["command"], "echo 'build'")

        # Verify JSON file written to disk
        json_file = Path(self.tmp_dir.name) / "test_build_pipeline.json"
        self.assertTrue(json_file.exists())

    def test_list_workflows(self):
        self.mgr.save_workflow(name="wf1", description="desc1", steps=[])
        self.mgr.save_workflow(name="wf2", description="desc2", steps=[])
        wfs = self.mgr.list_workflows()
        names = [w["name"] for w in wfs]
        self.assertIn("wf1", names)
        self.assertIn("wf2", names)

    def test_execute_workflow_tool_succeeds_and_goal_verified_satisfied(self):
        """TEST A: tool succeeds + goal verified -> SATISFIED."""
        self.mgr.save_workflow(
            name="echo_pipeline",
            description="Run echo pipeline",
            steps=[
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'step1'"}},
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'step2'"}},
            ],
        )
        rep = self.mgr.execute_workflow("echo_pipeline")
        self.assertTrue(rep.success)
        self.assertEqual(rep.status.value, "SATISFIED")
        self.assertEqual(len(rep.results), 2)
        self.assertEqual(len(rep.verifications), 2)

    def test_execute_workflow_tool_succeeds_but_state_not_achieved_unsatisfied(self):
        """TEST B: tool succeeds + state not achieved in OS -> UNSATISFIED."""
        # Launching a non-existent app: /usr/bin/open command might exit 0 or fail, but process is not running
        self.mgr.save_workflow(
            name="fake_launch_pipeline",
            description="Launch fake app",
            steps=[
                {"capability": "applications", "action": "launch_application", "args": {"application_name": "TotallyFakeApp999"}},
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'unreachable'"}},
            ],
        )
        rep = self.mgr.execute_workflow("fake_launch_pipeline")
        self.assertFalse(rep.success)
        self.assertEqual(rep.status.value, "UNSATISFIED")
        # Second step must not have been executed because first step was not satisfied!
        self.assertEqual(len(rep.results), 1)

    def test_execute_workflow_tool_succeeds_but_verification_unknown(self):
        """TEST C: tool succeeds + verification unavailable -> UNKNOWN."""
        from unittest.mock import patch
        from capabilities.base import ExecutionResult
        from verification.base import GoalStatus, VerificationResult

        self.mgr.save_workflow(
            name="mock_unknown_pipeline",
            description="Run unknown verification step",
            steps=[
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'mock'"}},
            ],
        )
        with patch("verification.evaluator.GoalEvaluator.evaluate_step") as mock_eval:
            mock_eval.return_value = VerificationResult(
                status=GoalStatus.UNKNOWN,
                explanation="No verification available",
            )
            rep = self.mgr.execute_workflow("mock_unknown_pipeline")
            self.assertFalse(rep.success)
            self.assertEqual(rep.status, GoalStatus.UNKNOWN)

    def test_execute_workflow_never_success_from_res_success_alone(self):
        """TEST D: workflow can never return successful overall status from res.success alone."""
        from unittest.mock import patch
        from capabilities.base import ExecutionResult
        from verification.base import GoalStatus, VerificationResult

        self.mgr.save_workflow(
            name="res_success_alone",
            description="Tool succeeds without goal satisfaction",
            steps=[
                {"capability": "terminal", "action": "execute_command", "args": {"command": "echo 'test'"}},
            ],
        )
        with patch("capabilities.registry.registry.execute") as mock_exec, \
             patch("verification.evaluator.GoalEvaluator.evaluate_step") as mock_eval:
            # Action returned tool success = True
            mock_exec.return_value = ExecutionResult(
                success=True,
                capability="terminal",
                action="execute_command",
            )
            # But verification could not confirm the goal
            mock_eval.return_value = VerificationResult(
                status=GoalStatus.UNSATISFIED,
                explanation="Goal condition not met",
            )
            rep = self.mgr.execute_workflow("res_success_alone")
            self.assertFalse(rep.success)
            self.assertEqual(rep.status, GoalStatus.UNSATISFIED)


if __name__ == "__main__":
    unittest.main()
