"""Structured UI target definitions and coordinate safety validation for MAX."""

import math
from pydantic import BaseModel, Field
from typing import Optional
from capabilities.vision.capture import DisplayInfo


class Point(BaseModel):
    x: float
    y: float

    def is_valid(self) -> bool:
        return not (math.isnan(self.x) or math.isnan(self.y) or math.isinf(self.x) or math.isinf(self.y))


class BoundingBox(BaseModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def center(self) -> Point:
        return Point(x=(self.x_min + self.x_max) / 2.0, y=(self.y_min + self.y_max) / 2.0)

    @property
    def width(self) -> float:
        return max(0.0, self.x_max - self.x_min)

    @property
    def height(self) -> float:
        return max(0.0, self.y_max - self.y_min)


class VisualTarget(BaseModel):
    description: str
    location: Point
    bounding_box: Optional[BoundingBox] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    display_id: int = 1
    text_label: Optional[str] = None
    is_sensitive: bool = False
    is_destructive: bool = False


# High-risk keywords that warrant confirmation even if vision confidence is high
DESTRUCTIVE_KEYWORDS = {
    "delete", "remove", "erase", "trash", "format", "wipe",
    "uninstall", "terminate", "kill", "shutdown", "reboot",
    "drop", "purge", "clear all", "reset", "overwrite"
}

SENSITIVE_KEYWORDS = {
    "password", "secret", "private key", "credit card", "cvv",
    "token", "ssn", "passphrase", "auth", "credential"
}


def validate_target_coordinates(point: Point, display: DisplayInfo) -> tuple[bool, str]:
    """Validate that coordinates are mathematically sound and lie strictly inside display bounds.
    
    Coordinates in macOS are measured in UI Points (e.g. 1470 x 956), not raw Retina pixels.
    """
    if not point.is_valid():
        return False, f"Invalid mathematical coordinates: ({point.x}, {point.y})"

    # Coordinates must be positive and strictly within display point dimensions
    if point.x < 0 or point.x > display.point_width:
        return False, f"X-coordinate {point.x} is out of bounds [0, {display.point_width}] for {display.name}"

    if point.y < 0 or point.y > display.point_height:
        return False, f"Y-coordinate {point.y} is out of bounds [0, {display.point_height}] for {display.name}"

    return True, "Valid"


def assess_target_risk(target: VisualTarget) -> tuple[bool, str]:
    """Evaluate target text and description for destructive or sensitive patterns."""
    text_corpus = f"{target.description} {target.text_label or ''}".lower()

    for kw in DESTRUCTIVE_KEYWORDS:
        if kw in text_corpus:
            target.is_destructive = True
            return True, f"Target matches destructive keyword '{kw}' - confirmation required."

    for kw in SENSITIVE_KEYWORDS:
        if kw in text_corpus:
            target.is_sensitive = True
            return True, f"Target matches sensitive keyword '{kw}' - caution required."

    return False, "Low risk"
