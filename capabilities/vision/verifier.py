"""Closed-loop visual verification for UI actions in MAX."""

import json
from pathlib import Path
from pydantic import BaseModel
import re
import time
from typing import Optional
from capabilities.vision.capture import capture_screen, CaptureResult
from capabilities.vision.provider import VisionProvider, OllamaVisionProvider
from verification.base import GoalStatus


class VisualVerificationResult(BaseModel):
    verified: bool
    status: str = GoalStatus.UNKNOWN.value
    screen_changed: bool
    explanation: str
    confidence: float = 0.0
    pre_capture_path: Optional[str] = None
    post_capture_path: Optional[str] = None
    duration_ms: float = 0.0
    error: Optional[str] = None


class ScreenVerifier:
    """Verifies whether an action resulted in the genuinely requested UI outcome."""

    def __init__(self, provider: Optional[VisionProvider] = None):
        self.provider = provider or OllamaVisionProvider()

    def _file_sizes_differ(self, path_a: str, path_b: str) -> bool:
        """Heuristic check: file size differences in compressed PNG indicate visual delta.

        NOTE: Screen change is strictly an OBSERVATION, never PROOF of goal satisfaction.
        """
        try:
            sz_a = Path(path_a).stat().st_size
            sz_b = Path(path_b).stat().st_size
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
        """Capture screen post-action and verify whether the intended UI change occurred.

        Never treats screen_changed as proof of success.
        If the vision model fails or returns malformed output, returns UNKNOWN.
        """
        start = time.time()

        # Allow UI animations/dialogs to settle
        if settle_delay_seconds > 0:
            time.sleep(settle_delay_seconds)

        # 1. Capture new post-action screenshot
        post_capture = capture_screen()
        if not post_capture.success:
            return VisualVerificationResult(
                verified=False,
                status=GoalStatus.UNKNOWN.value,
                screen_changed=False,
                explanation="Failed to capture post-action screenshot for verification.",
                error=post_capture.error,
                duration_ms=(time.time() - start) * 1000.0,
            )

        # Screen change is an observation only
        screen_changed = False
        if pre_capture and pre_capture.success and pre_capture.image_path:
            screen_changed = self._file_sizes_differ(pre_capture.image_path, post_capture.image_path)

        # 2. Query vision model to verify goal-specific state
        prompt = (
            f"An automated UI action was just performed targeting '{target_description}'.\n"
            f"Expected outcome: '{expected_change}'.\n\n"
            "Inspect the current screenshot. Has the expected UI state been achieved?\n"
            "Return JSON with format:\n"
            "{\n"
            '  "verified": true,\n'
            '  "explanation": "Factual description of what visible evidence confirms or refutes the expected outcome",\n'
            '  "confidence": 0.85\n'
            "}\n"
            "If the expected outcome is not visible or failed, return: {\"verified\": false, \"explanation\": \"...\"}."
        )

        resp = self.provider.analyze_image(post_capture.image_path, prompt, json_format=True)
        duration_ms = (time.time() - start) * 1000.0

        verified = False
        status = GoalStatus.UNKNOWN.value
        explanation = "Verification inconclusive."
        confidence = 0.0

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
                is_verified = bool(data.get("verified", False))
                explanation = data.get("explanation", raw)
                confidence = float(data.get("confidence", 0.8))

                if is_verified:
                    verified = True
                    status = GoalStatus.SATISFIED.value
                else:
                    verified = False
                    status = GoalStatus.UNSATISFIED.value
            else:
                # Malformed output from model -> UNKNOWN (never assume success or fallback to screen_changed)
                verified = False
                status = GoalStatus.UNKNOWN.value
                explanation = f"VLM returned unparseable or unstructured response: {raw[:120]}"
        else:
            # Model failed or unavailable -> UNKNOWN (never convert failure to success via screen diff)
            verified = False
            status = GoalStatus.UNKNOWN.value
            explanation = f"Vision provider query failed ({resp.error}). Verification status is UNKNOWN."

        result = VisualVerificationResult(
            verified=verified,
            status=status,
            screen_changed=screen_changed,
            explanation=explanation,
            confidence=confidence,
            pre_capture_path=pre_capture.image_path if pre_capture else None,
            post_capture_path=post_capture.image_path,
            duration_ms=duration_ms,
            error=resp.error if not resp.success else None,
        )

        # Discard temporary screenshot to maintain privacy
        post_capture.cleanup()

        return result
