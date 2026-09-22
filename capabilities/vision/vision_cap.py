"""Vision fallback capability for MAX agent."""

from pathlib import Path
import time
from typing import Any, Optional
from capabilities.base import Capability, Operation, ExecutionResult
from capabilities.vision.capture import capture_screen, get_connected_displays
from capabilities.vision.provider import VisionProvider, OllamaVisionProvider
from capabilities.vision.analyzer import ScreenAnalyzer
from capabilities.vision.actions import execute_click
from capabilities.vision.verifier import ScreenVerifier
from capabilities.vision.targets import Point, validate_target_coordinates
from security.risk import RiskLevel


class VisionCapability(Capability):
    """Computer-vision fallback capability for inspecting visible UI, finding targets, and executing verified actions."""

    name = "vision"
    description = (
        "Computer-vision fallback capability to visually inspect screens, locate UI elements, "
        "answer questions about visible content, and perform verified coordinate clicks when semantic automation is unavailable."
    )

    def __init__(self, provider: Optional[VisionProvider] = None):
        self.provider = provider or OllamaVisionProvider()
        self.analyzer = ScreenAnalyzer(self.provider)
        self.verifier = ScreenVerifier(self.provider)

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="describe_screen",
                description="Visually inspect and describe active application windows, menus, and controls on screen.",
                parameters={"display_id": "Optional display identifier (default: 1)"},
                default_risk=RiskLevel.LOW,
                handler=self.describe_screen,
            ),
            Operation(
                name="ask_screen",
                description="Ask a visual question about current screen contents or visible error messages.",
                parameters={
                    "question": "Question about the visible screen state",
                    "display_id": "Optional display identifier (default: 1)",
                },
                default_risk=RiskLevel.LOW,
                handler=self.ask_screen,
            ),
            Operation(
                name="find_visual_target",
                description="Locate a specific visual UI target (button, icon, link, input) and return its validated coordinates.",
                parameters={
                    "target_description": "Description of the UI element to locate (e.g. 'settings icon', 'Save button')",
                    "display_id": "Optional display identifier (default: 1)",
                },
                default_risk=RiskLevel.LOW,
                handler=self.find_visual_target,
            ),
            Operation(
                name="visual_click",
                description="Locate a visual target on screen and perform a safe, verified mouse click action.",
                parameters={
                    "target_description": "Description of the UI element to click",
                    "expected_outcome": "Expected visual change after clicking (e.g. 'settings modal opens')",
                    "click_type": "Optional: 'click' (default), 'double', or 'right'",
                    "display_id": "Optional display identifier (default: 1)",
                },
                default_risk=RiskLevel.MEDIUM,
                handler=self.visual_click,
            ),
            Operation(
                name="capture_screen",
                description="Capture a screenshot and return display metrics and capture metadata.",
                parameters={
                    "save_to_path": "Optional permanent file path to save screenshot",
                    "display_id": "Optional display identifier (default: 1)",
                },
                default_risk=RiskLevel.LOW,
                handler=self.capture_screen_op,
            ),
        ]

    def describe_screen(self, display_id: int = 1, **kwargs) -> ExecutionResult:
        """Capture screenshot and generate natural-language description."""
        cap = capture_screen(display_id=display_id)
        if not cap.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="describe_screen",
                error=cap.error or "Screen capture failed",
            )

        try:
            analysis = self.analyzer.describe_screen(cap.image_path)
            return ExecutionResult(
                success=analysis["success"],
                capability=self.name,
                action="describe_screen",
                data={"description": analysis.get("description", "")},
                evidence={
                    "model": analysis.get("model", ""),
                    "display": cap.display.model_dump(),
                    "duration_ms": analysis.get("duration_ms", 0.0),
                },
                verification={"screen_captured": True},
                error=analysis.get("error"),
            )
        finally:
            cap.cleanup()

    def ask_screen(self, question: str, display_id: int = 1, **kwargs) -> ExecutionResult:
        """Answer a specific question about visible screen contents."""
        cap = capture_screen(display_id=display_id)
        if not cap.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="ask_screen",
                error=cap.error or "Screen capture failed",
            )

        try:
            analysis = self.analyzer.answer_question(cap.image_path, question)
            return ExecutionResult(
                success=analysis["success"],
                capability=self.name,
                action="ask_screen",
                data={"question": question, "answer": analysis.get("answer", "")},
                evidence={
                    "model": analysis.get("model", ""),
                    "display": cap.display.model_dump(),
                    "duration_ms": analysis.get("duration_ms", 0.0),
                },
                verification={"screen_captured": True},
                error=analysis.get("error"),
            )
        finally:
            cap.cleanup()

    def find_visual_target(
        self, target_description: str, display_id: int = 1, **kwargs
    ) -> ExecutionResult:
        """Locate target element and return validated coordinates."""
        cap = capture_screen(display_id=display_id)
        if not cap.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="find_visual_target",
                error=cap.error or "Screen capture failed",
            )

        try:
            result = self.analyzer.find_target(cap.image_path, target_description, cap.display)
            if not result.found or not result.target:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="find_visual_target",
                    data={"target_description": target_description, "found": False},
                    evidence={"raw_response": result.raw_response},
                    error=result.error or f"Target '{target_description}' could not be located on screen",
                )

            return ExecutionResult(
                success=True,
                capability=self.name,
                action="find_visual_target",
                data={
                    "found": True,
                    "target": result.target.model_dump(),
                    "coordinates": {"x": result.target.location.x, "y": result.target.location.y},
                },
                evidence={
                    "confidence": result.target.confidence,
                    "display": cap.display.model_dump(),
                },
                verification={"coordinates_validated": True},
            )
        finally:
            cap.cleanup()

    def visual_click(
        self,
        target_description: str,
        expected_outcome: str = "UI updates or activates",
        click_type: str = "click",
        display_id: int = 1,
        **kwargs,
    ) -> ExecutionResult:
        """Execute a full closed-loop visual click with pre-action capture, action, and post-action verification."""
        # 1. Pre-action capture
        pre_cap = capture_screen(display_id=display_id)
        if not pre_cap.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="visual_click",
                error=pre_cap.error or "Screen capture failed prior to action",
            )

        try:
            # 2. Locate target
            search = self.analyzer.find_target(pre_cap.image_path, target_description, pre_cap.display)
            if not search.found or not search.target:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="visual_click",
                    data={"target_description": target_description, "found": False},
                    evidence={"search_error": search.error, "raw_response": search.raw_response},
                    error=f"Cannot click target: {search.error or 'Target not found on screen'}",
                )

            target = search.target

            # 3. Coordinate validation
            valid, err = validate_target_coordinates(target.location, pre_cap.display)
            if not valid:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="visual_click",
                    error=f"Refusing to click: {err}",
                )

            # 4. Perform click action
            action_res = execute_click(
                target.location,
                pre_cap.display,
                click_type=click_type,
                target=target,
            )

            if not action_res.success:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="visual_click",
                    data={"target": target.model_dump()},
                    error=action_res.error or "Native mouse click failed",
                )

            # 5. Settle and post-action verification
            verify_res = self.verifier.verify_action(
                target_description=target_description,
                expected_change=expected_outcome,
                pre_capture=pre_cap,
                settle_delay_seconds=0.6,
            )

            return ExecutionResult(
                success=verify_res.verified,
                capability=self.name,
                action="visual_click",
                data={
                    "target": target.model_dump(),
                    "action_executed": True,
                    "click_type": click_type,
                    "x": target.location.x,
                    "y": target.location.y,
                },
                evidence={
                    "action_duration_ms": action_res.duration_ms,
                    "verification_explanation": verify_res.explanation,
                    "screen_changed": verify_res.screen_changed,
                    "verification_confidence": verify_res.confidence,
                },
                verification={
                    "verified": verify_res.verified,
                    "screen_delta_detected": verify_res.screen_changed,
                    "explanation": verify_res.explanation,
                },
                error=None if verify_res.verified else f"Verification failed: {verify_res.explanation}",
            )

        finally:
            pre_cap.cleanup()

    def capture_screen_op(
        self, save_to_path: Optional[str] = None, display_id: int = 1, **kwargs
    ) -> ExecutionResult:
        """Capture screenshot and optionally save to user-specified path."""
        cap = capture_screen(output_path=save_to_path, display_id=display_id)
        if not cap.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="capture_screen",
                error=cap.error or "Screen capture failed",
            )

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="capture_screen",
            data={
                "saved_to": cap.image_path if save_to_path else None,
                "display": cap.display.model_dump(),
                "duration_ms": cap.duration_ms,
            },
            evidence={"display_metrics": cap.display.model_dump()},
            verification={"captured": True},
        )
