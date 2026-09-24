"""Tests for goal-driven execution and deterministic-first verification in MAX."""

import unittest
from unittest.mock import MagicMock, patch
from verification import GoalStatus, AgentState, GoalEvaluation, VerificationResult, goal_evaluator
from agent.core import AgentCore, StepExecutionRecord
from agent.planner import Plan, PlanStep
from agent.observer import EnvironmentObservation
from capabilities.base import ExecutionResult


class TestGoalVerification(unittest.TestCase):
    """Verify closed-loop goal evaluation contracts."""

    def setUp(self):
        self.agent = AgentCore()

    def test_deterministic_file_verification(self):
        """Verify write_file is verified by checking real file presence and size."""
        step = PlanStep(
            step_number=1,
            capability="filesystem",
            action="write_file",
            args={"path": "/tmp/max_test_verify.txt", "content": "hello world"},
        )
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")

        # Case A: File exists and has matching bytes
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.is_file", return_value=True), \
             patch("pathlib.Path.read_text", return_value="hello world"), \
             patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 11
            res = ExecutionResult(success=True, capability="filesystem", action="write_file")
            v_res = goal_evaluator.evaluate_step(step, res, obs)
            self.assertEqual(v_res.status, GoalStatus.SATISFIED)

        # Case B: File does not exist
        with patch("pathlib.Path.exists", return_value=False):
            res = ExecutionResult(success=True, capability="filesystem", action="write_file")
            v_res = goal_evaluator.evaluate_step(step, res, obs)
            self.assertEqual(v_res.status, GoalStatus.UNSATISFIED)

    def test_deterministic_application_verification(self):
        """Application launch must verify process presence, not just command success."""
        step = PlanStep(
            step_number=1,
            capability="applications",
            action="launch_application",
            args={"application_name": "Calculator"},
        )
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")

        # Open succeeded, but process is NOT in process list -> UNSATISFIED
        res_not_running = ExecutionResult(
            success=True,
            capability="applications",
            action="launch_application",
            verification={"process_present_in_process_list": False},
        )
        v_not_running = goal_evaluator.evaluate_step(step, res_not_running, obs)
        self.assertEqual(v_not_running.status, GoalStatus.UNSATISFIED)

        # Process is in process list -> SATISFIED
        res_running = ExecutionResult(
            success=True,
            capability="applications",
            action="launch_application",
            verification={"process_present_in_process_list": True},
        )
        v_running = goal_evaluator.evaluate_step(step, res_running, obs)
        self.assertEqual(v_running.status, GoalStatus.SATISFIED)

    def test_goal_evaluator_requires_all_mandatory_steps(self):
        """Goal is UNSATISFIED if required steps remain in the queue."""
        step1 = PlanStep(step_number=1, capability="terminal", action="execute_command", args={"command": "echo 1"})
        step2 = PlanStep(step_number=2, capability="terminal", action="execute_command", args={"command": "echo 2"})

        res1 = ExecutionResult(success=True, capability="terminal", action="execute_command")
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")
        verif1 = goal_evaluator.evaluate_step(step1, res1, obs)

        rec1 = StepExecutionRecord(
            step=step1,
            result=res1,
            observation_after={"active_application": "Finder"},
            verification=verif1,
        )

        # Only step 1 executed, step 2 remains
        goal_eval = goal_evaluator.evaluate_goal(
            user_request="Run two commands",
            steps_executed=[rec1],
            remaining_steps=[step2],
            last_observation=obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNSATISFIED)
        self.assertIn("1 required step(s) still remaining", goal_eval.explanation)

    def test_goal_unknown_when_step_verification_unknown(self):
        """When a required step has status UNKNOWN, goal must report UNKNOWN, not SUCCESS."""
        step1 = PlanStep(step_number=1, capability="vision", action="verify_action")
        res1 = ExecutionResult(
            success=True,
            capability="vision",
            action="verify_action",
            verification={"status": "UNKNOWN"},
        )
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")
        verif1 = goal_evaluator.evaluate_step(step1, res1, obs)
        self.assertEqual(verif1.status, GoalStatus.UNKNOWN)

        rec1 = StepExecutionRecord(
            step=step1,
            result=res1,
            observation_after={"active_application": "Finder"},
            verification=verif1,
        )

        goal_eval = goal_evaluator.evaluate_goal(
            user_request="Visually verify target",
            steps_executed=[rec1],
            remaining_steps=[],
            last_observation=obs,
        )
        self.assertEqual(goal_eval.status, GoalStatus.UNKNOWN)

    def test_agent_core_closed_loop_satisfaction(self):
        """AgentCore terminates with SATISFIED when all steps are verified."""
        mock_planner = MagicMock()
        mock_planner.create_plan.return_value = Plan(
            thought="Execute test command",
            plan=[
                PlanStep(step_number=1, capability="terminal", action="execute_command", args={"command": "echo hello"}),
            ]
        )
        mock_executor = MagicMock()
        mock_executor.execute_step.return_value = ExecutionResult(
            success=True,
            capability="terminal",
            action="execute_command",
            verification={"exit_code_zero": True},
        )

        agent = AgentCore(planner=mock_planner, executor=mock_executor)
        report = agent.run("Echo hello")

        self.assertEqual(report.goal_evaluation.status, GoalStatus.SATISFIED)
        self.assertEqual(report.state, AgentState.DONE)
        self.assertTrue(report.overall_success)
    def test_browser_unverified_action_returns_unknown(self):
        """Browser open_url action without tab/page verification returns UNKNOWN, never SATISFIED."""
        step = PlanStep(step_number=1, capability="browser", action="open_url", args={"url": "https://example.com"})
        res = ExecutionResult(success=True, capability="browser", action="open_url")
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Safari")
        v = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(v.status, GoalStatus.UNKNOWN)
        self.assertIn("no explicit tab/page state verification", v.explanation)

    def test_accessibility_unverified_action_returns_unknown(self):
        """Accessibility mutating click/shortcut action without GUI state verification returns UNKNOWN."""
        step = PlanStep(step_number=1, capability="accessibility", action="click_menu_item", args={"menu": "File", "item": "Save"})
        res = ExecutionResult(success=True, capability="accessibility", action="click_menu_item")
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")
        v = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(v.status, GoalStatus.UNKNOWN)
        self.assertIn("no explicit post-action GUI state verification", v.explanation)

    def test_macos_unverified_action_returns_unknown(self):
        """macOS show_notification action without state verification returns UNKNOWN."""
        step = PlanStep(step_number=1, capability="macos", action="show_notification", args={"message": "Done"})
        res = ExecutionResult(success=True, capability="macos", action="show_notification")
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")
        v = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(v.status, GoalStatus.UNKNOWN)
        self.assertIn("no explicit post-action state verification", v.explanation)

    def test_unhandled_capability_returns_unknown(self):
        """Arbitrary unhandled capability returns UNKNOWN, never SATISFIED merely because res.success=True."""
        step = PlanStep(step_number=1, capability="custom_extension", action="do_custom_thing", args={})
        res = ExecutionResult(success=True, capability="custom_extension", action="do_custom_thing")
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Finder")
        v = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(v.status, GoalStatus.UNKNOWN)
        self.assertIn("No explicit verification is implemented", v.explanation)


if __name__ == "__main__":
    unittest.main()
