"""Vision capability package for MAX."""

from .vision_cap import VisionCapability
from .capture import DisplayInfo, CaptureResult, get_connected_displays, capture_screen
from .targets import Point, BoundingBox, VisualTarget, validate_target_coordinates, assess_target_risk
from .provider import VisionProvider, OllamaVisionProvider, VisionResponse
from .analyzer import ScreenAnalyzer, TargetSearchResult
from .actions import execute_click, ActionOutcome
from .verifier import ScreenVerifier, VisualVerificationResult

__all__ = [
    "VisionCapability",
    "DisplayInfo",
    "CaptureResult",
    "get_connected_displays",
    "capture_screen",
    "Point",
    "BoundingBox",
    "VisualTarget",
    "validate_target_coordinates",
    "assess_target_risk",
    "VisionProvider",
    "OllamaVisionProvider",
    "VisionResponse",
    "ScreenAnalyzer",
    "TargetSearchResult",
    "execute_click",
    "ActionOutcome",
    "ScreenVerifier",
    "VisualVerificationResult",
]
