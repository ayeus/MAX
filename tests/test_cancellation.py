"""Tests for cancellation propagation and stuck-state watchdog recovery."""

import unittest
from unittest.mock import MagicMock, patch
import time
from verification import AgentState, GoalStatus
from agent.core import AgentCore
from agent.planner import Plan, PlanStep
from capabilities.base import ExecutionResult
from voice.assistant import VoiceAssistant, VoiceState, is_cancel_command


class TestCancellationAndRecovery(unittest.TestCase):
    """Verify that cancellation propagates cleanly and watchdog recovers stuck states."""

    def test_agent_cancellation_during_execution(self):
        """User cancellation must stop execution loop and transition to CANCELLED."""
        mock_planner = MagicMock()
        mock_planner.create_plan.return_value = Plan(
            thought="Long plan",
            plan=[
                PlanStep(step_number=1, capability="terminal", action="execute_command", args={"command": "sleep 10"}),
                PlanStep(step_number=2, capability="terminal", action="execute_command", args={"command": "echo done"}),
            ]
        )
        mock_executor = MagicMock()

        agent = AgentCore(planner=mock_planner, executor=mock_executor)

        # Trigger cancel during first step execution
        def execute_with_cancel(step):
            agent.cancel()
            return ExecutionResult(success=True, capability="terminal", action="execute_command")

        mock_executor.execute_step.side_effect = execute_with_cancel

        report = agent.run("Long sleep job")
        self.assertEqual(report.state, AgentState.CANCELLED)
        self.assertEqual(report.goal_evaluation.status, GoalStatus.UNKNOWN)
        self.assertFalse(report.overall_success)
        # Step 2 should never have executed
        self.assertEqual(len(report.steps_executed), 1)

    def test_voice_assistant_cancellation_detection(self):
        """Spoken 'stop' or 'cancel' triggers voice cancellation immediately."""
        self.assertTrue(is_cancel_command("stop"))
        self.assertTrue(is_cancel_command("cancel"))
        self.assertTrue(is_cancel_command("max stop"))
        self.assertTrue(is_cancel_command("max cancel"))
        self.assertTrue(is_cancel_command("abort"))
        self.assertFalse(is_cancel_command("open chrome"))
        self.assertFalse(is_cancel_command("stopwatch"))

    @patch("voice.assistant.stop_speaking")
    def test_voice_assistant_cancel_method(self, mock_stop_speak):
        """VoiceAssistant.cancel() aborts active agent and silences TTS."""
        mock_agent = MagicMock()
        assistant = VoiceAssistant(agent=mock_agent)
        assistant.set_state(VoiceState.EXECUTING)

        assistant.cancel()

        mock_agent.cancel.assert_called_once()
        mock_stop_speak.assert_called_once()
        self.assertEqual(assistant.state, VoiceState.IDLE)

    def test_voice_assistant_watchdog_recovery(self):
        """Watchdog detects stuck active state and recovers without process exit."""
        mock_agent = MagicMock()
        assistant = VoiceAssistant(agent=mock_agent)
        assistant.set_state(VoiceState.EXECUTING)
        # Simulate being stuck for 50 seconds
        assistant.state_updated_at = time.time() - 50.0

        recovered = assistant.check_watchdog(max_duration_seconds=40.0)
        self.assertTrue(recovered)
        mock_agent.cancel.assert_called_once()
        self.assertEqual(assistant.state, VoiceState.IDLE)


if __name__ == "__main__":
    unittest.main()
