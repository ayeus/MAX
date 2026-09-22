"""Closed-loop visual verification for UI actions in MAX."""

import json
from pathlib import Path
from pydantic import BaseModel
import re
import time
from typing import Optional
from capabilities.vision.capture import capture_screen, CaptureResult
from capabilities.vision.provider import VisionProvider, OllamaVisionProvider


class VisualVerificationResult(BaseModel):
    verified: bool
    screen_changed: bool
    explanation: str
    confidence: float = 0.0
    pre_capture_path: Optional[str] = None
    post_capture_path: Optional[str] = None
    duration_ms: float = 0.0
    error: Optional[str] = None


class ScreenVerifier:
    """Verifies that an action resulted in an observable UI transition or state change."""

    def __init__(self, provider: Optional[VisionProvider] = None):
        self.provider = provider or OllamaVisionProvider()

    def _file_sizes_differ(self, path_a: str, path_b: str) -> bool:
        """Heuristic check: file size differences in compressed PNG indicate visual delta."""
        try:
            sz_a = Path(path_a).stat().st_size
            sz_b = Path(path_b).stat().st_size
            # A difference of > 1KB in compressed PNG indicates visible UI changes
            return abs(sz_a - sz_b) > 1024
        except Exception:
            return False

    def verify_action(
        self,
        target_description: str,
        expected_change: str,
        pre_capture: Optional[CaptureResult] = None,
        settle_delay_seconds: float = 0.5,
    ) -> VisualVerificationResult:
        """Capture screen post-action and verify whether the intended UI change occurred."""
        start = time.time()

        # Allow UI animations/dialogs to settle
        if settle_delay_seconds > 0:
            time.sleep(settle_delay_seconds)

        # 1. Capture new post-action screenshot
        post_capture = capture_screen()
        if not post_capture.success:
            return VisualVerificationResult(
                verified=False,
                screen_changed=False,
                explanation="Failed to capture post-action screenshot for verification.",
                error=post_capture.error,
                duration_ms=(time.time() - start) * 1000.0,
            )

        screen_changed = False
        if pre_capture and pre_capture.success and pre_capture.image_path:
            screen_changed = self._file_sizes_differ(pre_capture.image_path, post_capture.image_path)

        # 2. Query vision model to verify state
        prompt = (
            f"An automated UI action was just performed targeting '{target_description}'.\n"
            f"Expected outcome: '{expected_change}'.\n\n"
            "Inspect the current screenshot. Has the expected UI state changed or been achieved?\n"
            "(For example: did a new window, modal, menu, or checkmark appear, or did the screen update?)\n"
            "Return JSON with format:\n"
            "{\n"
            '  "verified": true,\n'
            '  "explanation": "Brief description of what happened or is now visible",\n'
            '  "confidence": 0.85\n'
            "}\n"
            "If the expected outcome is not visible or failed, return: {\"verified\": false, \"explanation\": \"...\"}."
        )

        resp = self.provider.analyze_image(post_capture.image_path, prompt, json_format=True)
        duration_ms = (time.time() - start) * 1000.0

        verified = False
        explanation = "Verification completed."
        confidence = 0.5

        if resp.success:
            raw = resp.text.strip()
            data = None
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                match = re.search(r"\{[\s\S]*\}", raw)
                if match:
                    try:
                        data = json.loads(match.group(0))
                    except json.JSONDecodeError:
                        pass

            if isinstance(data, dict):
                verified = bool(data.get("verified", False))
                explanation = data.get("explanation", raw)
                confidence = float(data.get("confidence", 0.75))
            else:
                # If model returned text analysis
                if "yes" in raw.lower() or "verified" in raw.lower() or "opened" in raw.lower():
                    verified = True
                    explanation = raw
                else:
                    verified = screen_changed
                    explanation = raw
        else:
            # Fallback to physical screen diff if vision model fails
            verified = screen_changed
            explanation = (
                f"Vision verification query failed ({resp.error}), "
                f"but screen buffer {'changed' if screen_changed else 'remained identical'}."
            )

        result = VisualVerificationResult(
            verified=verified,
            screen_changed=screen_changed,
            explanation=explanation,
            confidence=confidence,
            pre_capture_path=pre_capture.image_path if pre_capture else None,
            post_capture_path=post_capture.image_path,
            duration_ms=duration_ms,
        )

        # Discard temporary screenshot to maintain privacy
        post_capture.cleanup()

        return result
