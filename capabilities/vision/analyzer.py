"""Screen analyzer for visual understanding, target identification, and VQA in MAX."""

import json
from pydantic import BaseModel
import re
from typing import Optional
from capabilities.vision.capture import DisplayInfo
from capabilities.vision.provider import VisionProvider, OllamaVisionProvider
from capabilities.vision.targets import (
    Point,
    BoundingBox,
    VisualTarget,
    validate_target_coordinates,
    assess_target_risk,
)


class TargetSearchResult(BaseModel):
    found: bool
    target: Optional[VisualTarget] = None
    raw_response: str = ""
    error: Optional[str] = None


class ScreenAnalyzer:
    """Performs visual inspection, target localization, and question answering on screenshots."""

    def __init__(self, provider: Optional[VisionProvider] = None):
        self.provider = provider or OllamaVisionProvider()

    def describe_screen(self, image_path: str) -> dict:
        """Provide a detailed natural-language description of visible windows, apps, and controls."""
        prompt = (
            "Describe what is currently visible on this macOS screen. "
            "Identify the active application windows, key UI elements, menus, open documents, "
            "and any notifications or error dialogs visible."
        )
        resp = self.provider.analyze_image(image_path, prompt)
        return {
            "success": resp.success,
            "description": resp.text,
            "model": resp.model,
            "duration_ms": resp.duration_ms,
            "error": resp.error,
        }

    def answer_question(self, image_path: str, question: str) -> dict:
        """Answer arbitrary questions about visible UI or screen contents."""
        q = question.strip()
        if "image" not in q.lower() and "screen" not in q.lower():
            prompt = f"{q.rstrip('?. ')} in this image?"
        elif "image" not in q.lower():
            prompt = f"{q} in this image"
        else:
            prompt = q

        resp = self.provider.analyze_image(image_path, prompt)
        return {
            "success": resp.success,
            "answer": resp.text,
            "model": resp.model,
            "duration_ms": resp.duration_ms,
            "error": resp.error,
        }

    def find_target(
        self,
        image_path: str,
        query: str,
        display: DisplayInfo,
        min_confidence: float = 0.4,
    ) -> TargetSearchResult:
        """Locate a specific visual target or UI element on screen."""
        prompt = (
            f"You are a computer vision assistant locating a UI element on a macOS screen.\n"
            f"Target to find: \"{query}\"\n\n"
            f"Locate the target element. Return ONLY valid JSON with this exact schema:\n"
            "{\n"
            '  "found": true,\n'
            '  "description": "Short description of the element found",\n'
            '  "normalized_x": 0.5,\n'
            '  "normalized_y": 0.3,\n'
            '  "box": [0.45, 0.28, 0.55, 0.32],\n'
            '  "confidence": 0.85,\n'
            '  "visible_text": "Text on the element"\n'
            "}\n"
            "Where normalized_x and normalized_y are floats from 0.0 (top-left) to 1.0 (bottom-right).\n"
            "If the element cannot be found on screen, return: {\"found\": false, \"reason\": \"Not visible\"}."
        )

        resp = self.provider.analyze_image(image_path, prompt, json_format=True)
        if not resp.success:
            return TargetSearchResult(
                found=False,
                raw_response=resp.text,
                error=resp.error or "Vision provider failed during target localization",
            )

        raw = resp.text.strip()
        data = None

        # 1. Try parsing JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try finding JSON block within backticks or braces
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass

        if not data or not isinstance(data, dict):
            # Parse text if model provided natural language coordinates
            norm_match = re.search(r"(?:x|center_x|point_x)[\"':\s]+([0-9\.]+).*?(?:y|center_y|point_y)[\"':\s]+([0-9\.]+)", raw, re.IGNORECASE)
            if norm_match:
                try:
                    data = {
                        "found": True,
                        "description": query,
                        "normalized_x": float(norm_match.group(1)),
                        "normalized_y": float(norm_match.group(2)),
                        "confidence": 0.7,
                    }
                except ValueError:
                    pass

        if not data:
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error="Could not parse structured target coordinates from vision model response",
            )

        if not data.get("found", False):
            reason = data.get("reason", "Element not visible or recognized on screen")
            return TargetSearchResult(found=False, raw_response=raw, error=reason)

        # Coordinate extraction
        nx = data.get("normalized_x")
        ny = data.get("normalized_y")

        if nx is None or ny is None:
            # Check for box [ymin, xmin, ymax, xmax] or [xmin, ymin, xmax, ymax]
            box = data.get("box") or data.get("bounding_box")
            if isinstance(box, list) and len(box) >= 4:
                nx = (float(box[0]) + float(box[2])) / 2.0
                ny = (float(box[1]) + float(box[3])) / 2.0

        if nx is None or ny is None:
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error="Model reported element found but provided no coordinates",
            )

        # Scale coordinates to macOS UI Points
        try:
            fx = float(nx)
            fy = float(ny)
        except (ValueError, TypeError):
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error=f"Malformed coordinate values: x={nx}, y={ny}",
            )

        # If values are normalized [0.0..1.0], map to display point dimensions
        if 0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0:
            target_x = round(fx * display.point_width, 1)
            target_y = round(fy * display.point_height, 1)
        elif fx > 1.0 and fy > 1.0:
            # Value might be in raw pixels
            if fx > display.point_width and display.scale_factor > 1.0:
                target_x = round(fx / display.scale_factor, 1)
                target_y = round(fy / display.scale_factor, 1)
            else:
                target_x = round(fx, 1)
                target_y = round(fy, 1)
        else:
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error=f"Unrecognized coordinate scale: x={fx}, y={fy}",
            )

        point = Point(x=target_x, y=target_y)

        # Validate coordinate boundaries against active display
        is_valid, validation_err = validate_target_coordinates(point, display)
        if not is_valid:
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error=f"Coordinate validation failed: {validation_err}",
            )

        conf = float(data.get("confidence", 0.75))
        if conf < min_confidence:
            return TargetSearchResult(
                found=False,
                raw_response=raw,
                error=f"Target confidence {conf:.2f} is below safety threshold {min_confidence:.2f}",
            )

        target = VisualTarget(
            description=data.get("description", query),
            location=point,
            confidence=min(1.0, max(0.0, conf)),
            display_id=display.display_id,
            text_label=data.get("visible_text"),
        )

        assess_target_risk(target)

        return TargetSearchResult(
            found=True,
            target=target,
            raw_response=raw,
        )
