"""Unit tests for AccessibilityCapability computer-use operations and verification."""

import unittest
from unittest.mock import patch, MagicMock
from capabilities.accessibility.accessibility import AccessibilityCapability
from capabilities.accessibility.models import ComputerState, UIElement
from capabilities.base import ExecutionResult
from agent.planner import PlanStep
from agent.observer import EnvironmentObservation
from verification.evaluator import goal_evaluator
from verification.base import GoalStatus


class TestComputerUseAccessibility(unittest.TestCase):
    def setUp(self):
        self.cap = AccessibilityCapability()
        self.sample_state = ComputerState(
            active_application="Notes",
            active_window_title="Notes",
            interactive_elements=[
                UIElement(role="AXButton", title="New Note", actions=["AXPress"]),
                UIElement(role="AXTextArea", description="note body", is_focused=True),
            ],
        )

    @patch("capabilities.accessibility.accessibility.tree_extractor.get_computer_state")
    def test_get_computer_state(self, mock_get_state):
        mock_get_state.return_value = self.sample_state
        res = self.cap.get_computer_state()
        self.assertTrue(res.success)
        self.assertEqual(res.data["active_application"], "Notes")
        self.assertEqual(len(res.data["interactive_controls"]), 2)

    @patch("capabilities.accessibility.accessibility.tree_extractor.get_computer_state")
    def test_find_element_success(self, mock_get_state):
        mock_get_state.return_value = self.sample_state
        res = self.cap.find_element(label="New Note", role="button")
        self.assertTrue(res.success)
        self.assertEqual(res.data["element"]["title"], "New Note")
        self.assertIn(res.data["confidence"], ("EXACT", "STRONG"))

    @patch("capabilities.accessibility.accessibility.tree_extractor.get_computer_state")
    def test_find_element_not_found(self, mock_get_state):
        mock_get_state.return_value = self.sample_state
        res = self.cap.find_element(label="Nonexistent Button")
        self.assertFalse(res.success)
        self.assertIn("No matching UI elements found", res.error)

    @patch("capabilities.accessibility.accessibility.tree_extractor.get_computer_state")
    @patch("capabilities.accessibility.accessibility.run_applescript")
    def test_click_element_success(self, mock_run_script, mock_get_state):
        mock_get_state.return_value = self.sample_state
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.stdout = "clicked_button"
        mock_res.stderr = ""
        mock_run_script.return_value = mock_res

        res = self.cap.click_element(label="New Note", role="button")
        self.assertTrue(res.success)
        self.assertTrue(res.verification.get("element_clicked"))

        # Verify deterministic evaluation
        step = PlanStep(step_number=1, capability="accessibility", action="click_element", args={"label": "New Note"})
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Notes")
        verif = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(verif.status, GoalStatus.SATISFIED)

    @patch("capabilities.accessibility.accessibility.tree_extractor.get_computer_state")
    @patch("capabilities.accessibility.accessibility.run_applescript")
    def test_type_into_element(self, mock_run_script, mock_get_state):
        mock_get_state.return_value = self.sample_state
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.stdout = ""
        mock_res.stderr = ""
        mock_run_script.return_value = mock_res

        res = self.cap.type_into_element(text="Hello world", target_label="note body", press_return=False)
        self.assertTrue(res.success)
        self.assertTrue(res.verification.get("typed_successfully"))
        self.assertEqual(res.data["text_length"], 11)

        # Verify deterministic evaluation
        step = PlanStep(step_number=2, capability="accessibility", action="type_into_element", args={"text": "Hello world", "target_label": "note body"})
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Notes")
        verif = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(verif.status, GoalStatus.SATISFIED)

    @patch("capabilities.accessibility.accessibility.run_applescript")
    def test_send_key_chord(self, mock_run_script):
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.stdout = ""
        mock_res.stderr = ""
        mock_run_script.return_value = mock_res

        res = self.cap.send_key_chord(key="s", modifiers="command")
        self.assertTrue(res.success)

        step = PlanStep(step_number=3, capability="accessibility", action="send_key_chord", args={"key": "s", "modifiers": "command"})
        obs = EnvironmentObservation(current_directory="/tmp", active_application="Notes")
        verif = goal_evaluator.evaluate_step(step, res, obs)
        self.assertEqual(verif.status, GoalStatus.SATISFIED)


if __name__ == "__main__":
    unittest.main()
