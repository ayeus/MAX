"""Unit and mocked tests for vision verification correctness."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from capabilities.vision.verifier import ScreenVerifier, VisualVerificationResult
from capabilities.vision.provider import VisionProvider, VisionResponse
from capabilities.vision.capture import CaptureResult, DisplayInfo
from verification.base import GoalStatus


class TestVisionCorrectness(unittest.TestCase):
    """Test strict visual verification rules."""

    def setUp(self):
        self.mock_display = DisplayInfo(
            display_id=1,
            pixel_width=2560,
            pixel_height=1600,
            points_width=1280.0,
            points_height=800.0,
            scale_factor=2.0,
        )

    def test_screen_changed_alone_is_not_verified(self):
        """ISSUE B1: Screen delta must NOT produce verified=True if goal is unsatisfied."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=True,
            text='{"verified": false, "explanation": "Target window did not open.", "confidence": 0.85}',
            model="moondream:latest",
        )

        with patch("capabilities.vision.verifier.capture_screen") as mock_cap, \
             patch.object(ScreenVerifier, "_file_sizes_differ", return_value=True):

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_p = Path(tmp.name)
                tmp_p.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            mock_cap.return_value = CaptureResult(
                success=True,
                image_path=str(tmp_p),
                display=self.mock_display,
            )
            pre_cap = CaptureResult(
                success=True,
                image_path=str(tmp_p),
                display=self.mock_display,
            )

            verifier = ScreenVerifier(provider=mock_provider)
            res = verifier.verify_action(
                target_description="Submit button",
                expected_change="Confirmation dialog appears",
                pre_capture=pre_cap,
                settle_delay_seconds=0.0,
            )

            # Even though screen_changed is True, verified must be FALSE!
            self.assertFalse(res.verified)
            self.assertEqual(res.status, GoalStatus.UNSATISFIED.value)
            self.assertTrue(res.screen_changed)

    def test_vision_provider_failure_returns_unknown(self):
        """ISSUE B2: Vision model failure must return UNKNOWN, never fallback to screen difference."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=False,
            text="",
            error="Connection to Ollama timed out after 15s",
            model="moondream:latest",
        )

        with patch("capabilities.vision.verifier.capture_screen") as mock_cap, \
             patch.object(ScreenVerifier, "_file_sizes_differ", return_value=True):

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_p = Path(tmp.name)
                tmp_p.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            mock_cap.return_value = CaptureResult(
                success=True,
                image_path=str(tmp_p),
                display=self.mock_display,
            )

            verifier = ScreenVerifier(provider=mock_provider)
            res = verifier.verify_action(
                target_description="Blastoise chat",
                expected_change="Chat window opens",
                settle_delay_seconds=0.0,
            )

            # MUST BE UNKNOWN, NOT SUCCESS!
            self.assertFalse(res.verified)
            self.assertEqual(res.status, GoalStatus.UNKNOWN.value)
            self.assertIn("Verification status is UNKNOWN", res.explanation)

    def test_malformed_vlm_output_returns_unknown(self):
        """ISSUE B5: Malformed VLM output must return UNKNOWN, never SUCCESS."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=True,
            text="I am unable to assist with this image or produce valid JSON.",
            model="moondream:latest",
        )

        with patch("capabilities.vision.verifier.capture_screen") as mock_cap:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_p = Path(tmp.name)
                tmp_p.write_bytes(b"\x89PNG\r\n\x1a\nfake")

            mock_cap.return_value = CaptureResult(
                success=True,
                image_path=str(tmp_p),
                display=self.mock_display,
            )

            verifier = ScreenVerifier(provider=mock_provider)
            res = verifier.verify_action(
                target_description="Search bar",
                expected_change="Cursor in search bar",
                settle_delay_seconds=0.0,
            )

            self.assertFalse(res.verified)
            self.assertEqual(res.status, GoalStatus.UNKNOWN.value)
            self.assertIn("unparseable", res.explanation)


if __name__ == "__main__":
    unittest.main()
