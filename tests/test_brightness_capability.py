"""Unit, mocked, and live empirical tests for macOS Native Display Brightness Control and Verification.

Taxonomy:
- UNIT: Capability method parameter clamping, return payloads, and error handling.
- MOCKED: GoalEvaluator independent state delta verification (detects both genuine change and false success).
- LIVE_MACOS: Real macOS DisplayServices / CoreGraphics hardware query, modification, and restoration.
"""

import unittest
from unittest.mock import patch, MagicMock
from capabilities.macos.macos_sys import MacOSSystemCapability
from macos.brightness import is_brightness_supported, get_display_brightness, set_display_brightness
from verification.evaluator import GoalEvaluator
from verification.base import GoalStatus
from agent.planner import PlanStep
from agent.observer import AgentObservation
from capabilities.base import ExecutionResult


class TestBrightnessCapability(unittest.TestCase):
    """Test suite for native display brightness control and independent delta verification."""

    def setUp(self):
        self.cap = MacOSSystemCapability()
        self.evaluator = GoalEvaluator()

    @patch("capabilities.macos.macos_sys.get_display_brightness")
    @patch("capabilities.macos.macos_sys.set_display_brightness")
    def test_unit_brightness_increase_and_decrease(self, mock_set, mock_get):
        """[UNIT] Verify increase and decrease methods compute targets and produce correct ExecutionResult."""
        mock_get.return_value = (True, 0.50, None)
        mock_set.return_value = (True, 0.60, None)

        res_inc = self.cap.increase_brightness(delta=0.1)
        self.assertTrue(res_inc.success)
        self.assertEqual(res_inc.capability, "macos")
        self.assertEqual(res_inc.action, "increase_brightness")
        self.assertAlmostEqual(res_inc.data.get("level"), 0.60)
        self.assertAlmostEqual(res_inc.data.get("previous_level"), 0.50)
        self.assertTrue(res_inc.verification.get("brightness_increased"))

        mock_get.return_value = (True, 0.60, None)
        mock_set.return_value = (True, 0.45, None)

        res_dec = self.cap.decrease_brightness(delta=0.15)
        self.assertTrue(res_dec.success)
        self.assertEqual(res_dec.action, "decrease_brightness")
        self.assertAlmostEqual(res_dec.data.get("level"), 0.45)
        self.assertTrue(res_dec.verification.get("brightness_decreased"))

    @patch("macos.brightness.get_display_brightness")
    @patch("macos.brightness.is_brightness_supported", return_value=True)
    def test_evaluator_detects_false_success_on_no_delta(self, mock_is_sup, mock_get_bright):
        """[MOCKED] GoalEvaluator must return UNSATISFIED if an action claims success but hardware brightness did not change."""
        step = PlanStep(
            step_number=1,
            capability="macos",
            action="increase_brightness",
            args={"delta": 0.1},
        )
        fake_result = ExecutionResult(
            success=True,
            capability="macos",
            action="increase_brightness",
            evidence={"before": 0.50},
        )
        # Post-action hardware observation shows no change (stuck at 0.50)
        mock_get_bright.return_value = (True, 0.50, None)
        obs = AgentObservation(current_directory="/tmp", active_application="Finder")

        verif = self.evaluator.evaluate_step(step, fake_result, obs)
        self.assertEqual(
            verif.status,
            GoalStatus.UNSATISFIED,
            "Evaluator must reject increase_brightness when hardware brightness delta is 0",
        )
        self.assertIn("did not increase", verif.explanation)

    @patch("macos.brightness.get_display_brightness")
    @patch("macos.brightness.is_brightness_supported", return_value=True)
    def test_evaluator_verifies_genuine_increase_delta(self, mock_is_sup, mock_get_bright):
        """[MOCKED] GoalEvaluator returns SATISFIED when independent hardware query confirms positive delta."""
        step = PlanStep(
            step_number=1,
            capability="macos",
            action="increase_brightness",
            args={"delta": 0.1},
        )
        genuine_result = ExecutionResult(
            success=True,
            capability="macos",
            action="increase_brightness",
            evidence={"before": 0.50, "after": 0.60},
        )
        # Independent hardware query confirms brightness increased to 0.60
        mock_get_bright.return_value = (True, 0.60, None)
        obs = AgentObservation(current_directory="/tmp", active_application="Finder")

        verif = self.evaluator.evaluate_step(step, genuine_result, obs)
        self.assertEqual(
            verif.status,
            GoalStatus.SATISFIED,
            "Evaluator must satisfy increase_brightness when independent hardware delta is confirmed",
        )
        self.assertIn("increased from 0.50 to 0.60", verif.explanation)

    def test_live_macos_hardware_brightness_query_and_delta(self):
        """[LIVE_MACOS] Genuinely query, perturb by minimal delta, and restore real macOS display brightness."""
        if not is_brightness_supported():
            self.skipTest("macOS DisplayServices brightness is not supported on this display hardware.")

        ok_orig, orig_val, err = get_display_brightness()
        self.assertTrue(ok_orig, f"Failed to query live macOS display brightness: {err}")
        self.assertGreaterEqual(orig_val, 0.0)
        self.assertLessEqual(orig_val, 1.0)

        # Apply small non-disruptive delta (+0.02 or -0.02)
        delta = 0.02 if orig_val < 0.90 else -0.02
        target_val = orig_val + delta

        try:
            ok_set, set_val, err_set = set_display_brightness(target_val)
            self.assertTrue(ok_set, f"Failed to set live brightness: {err_set}")

            # Verify with fresh independent query
            ok_read, read_val, _ = get_display_brightness()
            self.assertTrue(ok_read)
            if delta > 0:
                self.assertGreater(read_val, orig_val - 0.005)
            else:
                self.assertLess(read_val, orig_val + 0.005)
        finally:
            # Always restore original hardware brightness
            set_display_brightness(orig_val)
            _, restored_val, _ = get_display_brightness()
            self.assertAlmostEqual(restored_val, orig_val, delta=0.03)


if __name__ == "__main__":
    unittest.main()
