"""Unit, mocked, and integration tests for MAX Hard Capability Availability Gating.

Taxonomy:
- UNIT: Planner hard gate for unsupported hardware/system capabilities.
- MOCKED: Capability registry rejection of unregistered hallucinated operations.
- INTEGRATION: AgentCore transitions to AgentState.UNSUPPORTED with GoalStatus.UNSUPPORTED.
"""

import unittest
from unittest.mock import MagicMock, patch
from agent.planner import Planner, Plan, PlanStep
from agent.core import AgentCore
from agent.context import AgentContext
from agent.observer import AgentObservation
from verification.base import GoalStatus, AgentState
from capabilities.registry import CapabilityRegistry, registry


class TestUnsupportedGate(unittest.TestCase):
    """Test suite ensuring MAX never hallucinates execution of unsupported capabilities."""

    def setUp(self):
        self.planner = Planner()
        self.context = AgentContext(
            observation=AgentObservation(current_directory="/tmp", active_application="Finder"),
            recent_history=[],
        )

    def test_planner_unsupported_hardware_requests(self):
        """[UNIT] Planner immediately returns empty plan with truthful explanation for unsupported hardware features."""
        unsupported_requests = [
            "Change my monitor refresh rate to 120Hz",
            "Set display refresh rate to 60 Hz",
            "Overclock my CPU to 5.0 GHz",
            "Increase fan speed to maximum RPM",
            "Pair bluetooth headphones with my Mac",
            "Enable Night Shift mode",
            "Toggle True Tone on my screen",
        ]
        for req in unsupported_requests:
            plan = self.planner.create_plan(req, self.context)
            self.assertEqual(
                len(plan.plan),
                0,
                f"Expected 0 steps for unsupported request '{req}', got {len(plan.plan)}",
            )
            self.assertTrue(
                any(w in plan.thought.lower() for w in ("don't have a supported", "cannot perform", "unsupported", "can't")),
                f"Plan thought did not explain unsupported capability truthfully: '{plan.thought}'",
            )

    @patch("agent.planner.model_manager")
    def test_planner_rejects_hallucinated_unregistered_operations(self, mock_mm):
        """[MOCKED] Planner filters out hallucinated operations not present in CapabilityRegistry."""
        mock_provider = MagicMock()
        # Simulate an LLM that outputs a fabricated unregistered capability
        mock_response = MagicMock()
        mock_response.content = (
            '{"thought": "Adjusting refresh rate", "plan": ['
            '{"capability": "display_hardware", "action": "set_refresh_rate", "args": {"hz": 120}},'
            '{"capability": "macos", "action": "show_notification", "args": {"message": "Done"}}'
            ']}'
        )
        mock_provider.generate.return_value = mock_response
        planner = Planner(provider=mock_provider)

        # Bypass fast-path so mock LLM is called
        plan = planner.create_plan("Configure extreme monitor settings", self.context)

        # 'display_hardware.set_refresh_rate' is NOT registered, so it must be stripped
        actions = [f"{s.capability}.{s.action}" for s in plan.plan]
        self.assertNotIn("display_hardware.set_refresh_rate", actions)
        # 'macos.show_notification' IS registered, so it remains valid
        self.assertIn("macos.show_notification", actions)

    def test_agent_core_unsupported_lifecycle(self):
        """[INTEGRATION] AgentCore must cleanly transition to UNSUPPORTED state with 0 false successes."""
        agent = AgentCore()
        report = agent.run("Please set my screen refresh rate to 144Hz")

        self.assertEqual(
            report.state,
            AgentState.UNSUPPORTED,
            f"Expected AgentState.UNSUPPORTED, got {report.state}",
        )
        self.assertEqual(
            report.goal_evaluation.status,
            GoalStatus.UNSUPPORTED,
            f"Expected GoalStatus.UNSUPPORTED, got {report.goal_evaluation.status}",
        )
        self.assertFalse(report.overall_success)
        self.assertEqual(len(report.steps_executed), 0)
        self.assertIn("UNSUPPORTED", report.final_summary)


if __name__ == "__main__":
    unittest.main()
