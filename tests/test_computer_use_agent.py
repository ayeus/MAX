"""Unit tests for AgentCore closed-loop multi-step computer use."""

import unittest
from unittest.mock import MagicMock, patch
from agent.core import AgentCore
from agent.planner import Plan, PlanStep
from agent.observer import EnvironmentObservation
from capabilities.base import ExecutionResult
from verification.base import GoalStatus, GoalEvaluation


class TestComputerUseAgent(unittest.TestCase):
    def test_goal_evaluator_rejects_premature_completion_when_interaction_requested(self):
        """If user asks to open an app and message/type, launching the app alone is not SATISFIED."""
        from verification.evaluator import goal_evaluator

        step1 = PlanStep(step_number=1, capability="applications", action="launch_application", args={"application_name": "WhatsApp"})
        res1 = ExecutionResult(
            success=True,
            capability="applications",
            action="launch_application",
            verification={"process_present_in_process_list": True},
        )
        obs1 = EnvironmentObservation(current_directory="/tmp", active_application="WhatsApp")

        rec1 = MagicMock()
        rec1.step = step1
        rec1.result = res1
        rec1.verification = goal_evaluator.evaluate_step(step1, res1, obs1)

        eval_res = goal_evaluator.evaluate_goal(
            user_request="Open WhatsApp and message John saying I will be 10 minutes late",
            steps_executed=[rec1],
            remaining_steps=[],
            last_observation=obs1,
        )

        self.assertEqual(eval_res.status, GoalStatus.UNSATISFIED)
        self.assertIn("requested action inside the application", eval_res.explanation)

    @patch("agent.core.assemble_context")
    @patch("agent.core.observer.observe")
    def test_agent_core_multi_step_continuation(self, mock_observe, mock_context):
        """AgentCore continues planning when queue is empty but goal requires subsequent interaction."""
        mock_planner = MagicMock()
        mock_executor = MagicMock()

        # Step 1: Launch application
        step1 = PlanStep(step_number=1, capability="applications", action="launch_application", args={"application_name": "TextEdit"})
        res1 = ExecutionResult(
            success=True,
            capability="applications",
            action="launch_application",
            verification={"process_present_in_process_list": True},
        )

        # Step 2: Continuation step produced by planner
        step2 = PlanStep(step_number=2, capability="accessibility", action="type_into_element", args={"text": "Meeting notes", "target_label": "text entry area"})
        res2 = ExecutionResult(
            success=True,
            capability="accessibility",
            action="type_into_element",
            data={"text_length": 13, "target_label": "text entry area"},
            verification={"typed_successfully": True},
        )

        # First call to planner produces step 1
        plan1 = Plan(thought="Launch TextEdit first", plan=[step1])
        # Second call to planner (continuation) produces step 2
        plan2 = Plan(thought="Now type the notes into the text area", plan=[step2])
        # Third call: Phase 13 fix causes replan after type_into_element returns UNKNOWN
        # (no independent post-state evidence in mocked env). Empty plan signals completion.
        plan3 = Plan(thought="All steps completed", plan=[])
        mock_planner.create_plan.side_effect = [plan1, plan2, plan3]

        mock_executor.execute_step.side_effect = [res1, res2]

        obs = EnvironmentObservation(
            current_directory="/tmp",
            active_application="TextEdit",
            active_window="Untitled",
            ui_summary={"interactive_controls": [{"role": "AXTextArea", "description": "text entry area"}]},
        )
        mock_observe.return_value = obs

        mock_ctx = MagicMock()
        mock_ctx.observation = obs
        mock_context.return_value = mock_ctx

        agent = AgentCore(planner=mock_planner, executor=mock_executor)
        # Phase 13: step_verif UNKNOWN triggers state-driven replanning (line 286-299 in core.py).
        # Mock replanner to return None so no spurious recovery steps are generated.
        agent.replanner = MagicMock()
        agent.replanner.determine_recovery_step.return_value = None
        report = agent.run("Open TextEdit and type meeting notes")

        # Phase 13: type_into_element without independent post-action ComputerState
        # may return UNKNOWN. The test verifies the multi-step continuation mechanism
        # works correctly, not that mocked results are independently verifiable.
        self.assertTrue(report.overall_success or report.goal_evaluation.status in (GoalStatus.SATISFIED, GoalStatus.UNKNOWN))
        self.assertIn(report.goal_evaluation.status, (GoalStatus.SATISFIED, GoalStatus.UNKNOWN))
        self.assertEqual(len(report.steps_executed), 2)
        self.assertEqual(report.steps_executed[0].step.action, "launch_application")
        self.assertEqual(report.steps_executed[1].step.action, "type_into_element")


if __name__ == "__main__":
    unittest.main()
