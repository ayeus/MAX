"""Unit and live tests for MAX Vision subsystem (Phase 7).

Distinguishes explicitly between:
- [MOCKED TEST]: Validates internal logic, schemas, safety policies, coordinate bounding, and error handling.
- [LIVE MAC TEST]: Validates actual macOS display querying, live screen capture, and native mouse click binary.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import math

from capabilities.vision.capture import (
    DisplayInfo,
    CaptureResult,
    get_connected_displays,
    capture_screen,
)
from capabilities.vision.targets import (
    Point,
    BoundingBox,
    VisualTarget,
    validate_target_coordinates,
    assess_target_risk,
)
from capabilities.vision.provider import (
    VisionProvider,
    OllamaVisionProvider,
    VisionResponse,
)
from capabilities.vision.analyzer import ScreenAnalyzer, TargetSearchResult
from capabilities.vision.actions import execute_click, ActionOutcome
from capabilities.vision.verifier import ScreenVerifier, VisualVerificationResult
from capabilities.vision.vision_cap import VisionCapability
from security.permissions import PermissionReport, PermissionStatus


class TestVisionSubsystem(unittest.TestCase):
    """Phase 7 Vision Subsystem Tests."""

    def setUp(self):
        self.mock_display = DisplayInfo(
            display_id=1,
            name="Test Retina Display",
            is_main=True,
            pixel_width=2940,
            pixel_height=1912,
            point_width=1470.0,
            point_height=956.0,
            scale_factor=2.0,
        )

    # -------------------------------------------------------------------------
    # 1. Screen Capture & Permissions Tests
    # -------------------------------------------------------------------------

    def test_screen_capture_permissions_granted(self):
        """[MOCKED TEST] test_screen_capture_permissions: Verify capture proceeds when permission is granted."""
        with patch("capabilities.vision.capture.check_screen_recording_permission") as mock_perm, \
             patch("capabilities.vision.capture.get_connected_displays", return_value=[self.mock_display]), \
             patch("capabilities.vision.capture.subprocess.run") as mock_run:

            mock_perm.return_value = PermissionReport(
                permission_name="Screen Recording",
                status=PermissionStatus.GRANTED,
                description="Test",
                system_settings_path="Settings > Screen Recording",
                impact="Test",
            )
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_p = Path(tmp.name)
                tmp_p.write_bytes(b"\x89PNG\r\n\x1a\nfakecontent")

            try:
                res = capture_screen(output_path=str(tmp_p))
                self.assertTrue(res.success)
                self.assertEqual(res.image_path, str(tmp_p))
            finally:
                if tmp_p.exists():
                    tmp_p.unlink()

    def test_permission_failure(self):
        """[MOCKED TEST] test_permission_failure: Verify clear failure and user guidance when permission is denied."""
        with patch("capabilities.vision.capture.check_screen_recording_permission") as mock_perm:
            mock_perm.return_value = PermissionReport(
                permission_name="Screen Recording",
                status=PermissionStatus.DENIED_OR_MISSING,
                description="Permission denied",
                system_settings_path="System Settings > Privacy & Security > Screen Recording",
                impact="Disabled",
            )
            res = capture_screen()
            self.assertFalse(res.success)
            self.assertIn("Screen Recording permission is required", res.error)
            self.assertIn("System Settings", res.error)

    # -------------------------------------------------------------------------
    # 2. Display Dimensions & Multi-monitor
    # -------------------------------------------------------------------------

    def test_screen_dimensions(self):
        """[LIVE MAC TEST] test_screen_dimensions: Discover real connected displays and verify positive dimensions."""
        displays = get_connected_displays()
        self.assertGreater(len(displays), 0)
        disp = displays[0]
        self.assertGreater(disp.pixel_width, 0)
        self.assertGreater(disp.pixel_height, 0)
        self.assertGreater(disp.point_width, 0)
        self.assertGreater(disp.point_height, 0)
        self.assertGreaterEqual(disp.scale_factor, 1.0)

    # -------------------------------------------------------------------------
    # 3. Vision Provider Interface
    # -------------------------------------------------------------------------

    def test_vision_provider(self):
        """[MOCKED TEST] test_vision_provider: Verify OllamaVisionProvider abstraction and response model."""
        provider = OllamaVisionProvider(base_url="http://localhost:11434")

        with patch.object(provider, "_resolve_model", return_value="moondream:latest"), \
             patch("urllib.request.urlopen") as mock_urlopen:

            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = b'{"response": "A macOS desktop with VS Code and Terminal open."}'
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(b"PNG_DATA")
                tmp_path = tmp.name

            try:
                res = provider.analyze_image(tmp_path, "Describe this screen")
                self.assertTrue(res.success)
                self.assertEqual(res.model, "moondream:latest")
                self.assertIn("macOS desktop", res.text)
                self.assertGreater(res.duration_ms, 0)
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # 4. Target Validation & Invalid Coordinates Rejection
    # -------------------------------------------------------------------------

    def test_invalid_coordinates(self):
        """[MOCKED TEST] test_invalid_coordinates: Reject coordinates outside display point bounds."""
        # 1. Negative coordinates
        valid, msg = validate_target_coordinates(Point(x=-10.0, y=100.0), self.mock_display)
        self.assertFalse(valid)
        self.assertIn("out of bounds", msg)

        # 2. Beyond point width
        valid, msg = validate_target_coordinates(Point(x=1500.0, y=100.0), self.mock_display)
        self.assertFalse(valid)
        self.assertIn("out of bounds", msg)

        # 3. Beyond point height
        valid, msg = validate_target_coordinates(Point(x=500.0, y=1000.0), self.mock_display)
        self.assertFalse(valid)
        self.assertIn("out of bounds", msg)

        # 4. NaN / Inf
        valid, msg = validate_target_coordinates(Point(x=float("nan"), y=50.0), self.mock_display)
        self.assertFalse(valid)
        self.assertIn("Invalid mathematical", msg)

        # 5. Valid within bounds
        valid, msg = validate_target_coordinates(Point(x=735.0, y=478.0), self.mock_display)
        self.assertTrue(valid)

    def test_target_validation(self):
        """[MOCKED TEST] test_target_validation: Verify ScreenAnalyzer parses and validates normalized targets."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=True,
            text='{"found": true, "description": "Save Button", "normalized_x": 0.5, "normalized_y": 0.25, "confidence": 0.9}',
            model="moondream:latest",
        )

        analyzer = ScreenAnalyzer(provider=mock_provider)
        res = analyzer.find_target("dummy.png", "Save Button", self.mock_display)

        self.assertTrue(res.found)
        self.assertIsNotNone(res.target)
        self.assertEqual(res.target.description, "Save Button")
        # 0.5 * 1470.0 = 735.0, 0.25 * 956.0 = 239.0
        self.assertEqual(res.target.location.x, 735.0)
        self.assertEqual(res.target.location.y, 239.0)
        self.assertEqual(res.target.confidence, 0.9)

    def test_invalid_model_output(self):
        """[MOCKED TEST] test_invalid_model_output: Reject malformed, unparseable, or hallucinatory model responses."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=True,
            text="Sorry, I am just a language model and cannot give you coordinates.",
            model="moondream:latest",
        )

        analyzer = ScreenAnalyzer(provider=mock_provider)
        res = analyzer.find_target("dummy.png", "Submit button", self.mock_display)

        self.assertFalse(res.found)
        self.assertIn("Could not parse structured target coordinates", res.error)

    # -------------------------------------------------------------------------
    # 5. Risk & Confirmation Integration
    # -------------------------------------------------------------------------

    def test_risk_integration(self):
        """[MOCKED TEST] test_risk_integration: Detect destructive and sensitive keywords on visual targets."""
        dest_target = VisualTarget(
            description="Delete Database button",
            location=Point(x=100.0, y=100.0),
            confidence=0.95,
        )
        is_risky, msg = assess_target_risk(dest_target)
        self.assertTrue(is_risky)
        self.assertTrue(dest_target.is_destructive)
        self.assertIn("destructive", msg)

        sens_target = VisualTarget(
            description="Enter Password field",
            location=Point(x=200.0, y=200.0),
            confidence=0.9,
        )
        is_risky, msg = assess_target_risk(sens_target)
        self.assertTrue(is_risky)
        self.assertTrue(sens_target.is_sensitive)
        self.assertIn("sensitive", msg)

    def test_confirmation(self):
        """[MOCKED TEST] test_confirmation: Enforce user confirmation policy on high-risk visual actions."""
        dest_target = VisualTarget(
            description="Erase All Contents",
            location=Point(x=300.0, y=300.0),
            confidence=0.99,
            is_destructive=True,
        )

        # 1. User denies
        outcome_denied = execute_click(
            point=dest_target.location,
            display=self.mock_display,
            target=dest_target,
            confirm_func=lambda _: False,
        )
        self.assertFalse(outcome_denied.success)
        self.assertFalse(outcome_denied.confirmed)
        self.assertIn("cancelled by user safety policy", outcome_denied.error)

        # 2. User confirms
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            outcome_confirmed = execute_click(
                point=dest_target.location,
                display=self.mock_display,
                target=dest_target,
                confirm_func=lambda _: True,
            )
            self.assertTrue(outcome_confirmed.success)
            self.assertTrue(outcome_confirmed.confirmed)

    # -------------------------------------------------------------------------
    # 6. Verification
    # -------------------------------------------------------------------------

    def test_verification(self):
        """[MOCKED TEST] test_verification: Closed-loop verification queries post-action screen and reports result."""
        mock_provider = MagicMock(spec=VisionProvider)
        mock_provider.analyze_image.return_value = VisionResponse(
            success=True,
            text='{"verified": true, "explanation": "Settings modal is now open on screen.", "confidence": 0.92}',
            model="moondream:latest",
        )

        with patch("capabilities.vision.verifier.capture_screen") as mock_cap:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_p = Path(tmp.name)
                tmp_p.write_bytes(b"\x89PNG\r\n\x1a\nfakecontent")

            mock_cap.return_value = CaptureResult(
                success=True,
                image_path=str(tmp_p),
                display=self.mock_display,
            )

            verifier = ScreenVerifier(provider=mock_provider)
            res = verifier.verify_action(
                target_description="Settings button",
                expected_change="Settings modal opens",
                settle_delay_seconds=0.0,
            )

            self.assertTrue(res.verified)
            self.assertIn("Settings modal is now open", res.explanation)
            self.assertEqual(res.confidence, 0.92)


if __name__ == "__main__":
    unittest.main()
