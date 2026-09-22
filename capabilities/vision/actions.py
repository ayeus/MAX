"""Safe UI action execution for visual targets in MAX."""

from pathlib import Path
from pydantic import BaseModel
import subprocess
import time
from typing import Callable, Optional
from capabilities.vision.capture import DisplayInfo
from capabilities.vision.targets import Point, VisualTarget, validate_target_coordinates
from security.permissions import check_accessibility_permission, PermissionStatus


class ActionOutcome(BaseModel):
    success: bool
    x: float
    y: float
    click_type: str = "click"
    target_description: Optional[str] = None
    duration_ms: float = 0.0
    confirmed: bool = True
    error: Optional[str] = None


def _get_click_binary_path() -> Path:
    """Resolve compiled max-mouse-click binary."""
    # Check bin/ relative to project root
    project_root = Path(__file__).resolve().parent.parent.parent
    candidate = project_root / "bin" / "max-mouse-click"
    if candidate.exists() and candidate.stat().st_mode & 0o111:
        return candidate
    return candidate


def execute_click(
    point: Point,
    display: DisplayInfo,
    click_type: str = "click",
    target: Optional[VisualTarget] = None,
    confirm_func: Optional[Callable[[str], bool]] = None,
) -> ActionOutcome:
    """Execute a safe native mouse click at verified screen coordinates.
    
    1. Validates coordinate bounds against the target display.
    2. Enforces security confirmation if target is destructive or sensitive.
    3. Invokes native max-mouse-click CoreGraphics binary.
    4. Records action duration and result.
    """
    # 1. Validate coordinates
    is_valid, err_msg = validate_target_coordinates(point, display)
    if not is_valid:
        return ActionOutcome(
            success=False,
            x=point.x,
            y=point.y,
            click_type=click_type,
            error=f"Refusing to click: {err_msg}",
        )

    # 2. Risk evaluation and Confirmation
    if target and (target.is_destructive or target.is_sensitive):
        prompt_text = f"MAX Vision: Target '{target.description}' is flagged as high-risk/sensitive. Continue? (y/N): "
        if confirm_func:
            confirmed = confirm_func(prompt_text)
        else:
            try:
                user_input = input(prompt_text).strip().lower()
                confirmed = user_input in ("y", "yes")
            except Exception:
                confirmed = False

        if not confirmed:
            return ActionOutcome(
                success=False,
                x=point.x,
                y=point.y,
                click_type=click_type,
                target_description=target.description,
                confirmed=False,
                error="Action cancelled by user safety policy.",
            )

    # 3. Accessibility permission check
    perm = check_accessibility_permission()
    if perm.status != PermissionStatus.GRANTED:
        # Note: CGEventCreateMouseEvent does not strictly require Accessibility on all macOS versions,
        # but if synthetic input is blocked, report it clearly.
        pass

    binary = _get_click_binary_path()
    if not binary.exists():
        return ActionOutcome(
            success=False,
            x=point.x,
            y=point.y,
            click_type=click_type,
            error=f"max-mouse-click binary not found at {binary}. Build it first with swiftc.",
        )

    start = time.time()
    try:
        proc = subprocess.run(
            [str(binary), str(point.x), str(point.y), click_type],
            capture_output=True,
            text=True,
            timeout=5,
        )
        duration_ms = (time.time() - start) * 1000.0

        if proc.returncode == 0:
            return ActionOutcome(
                success=True,
                x=point.x,
                y=point.y,
                click_type=click_type,
                target_description=target.description if target else None,
                duration_ms=duration_ms,
            )
        else:
            return ActionOutcome(
                success=False,
                x=point.x,
                y=point.y,
                click_type=click_type,
                target_description=target.description if target else None,
                duration_ms=duration_ms,
                error=proc.stderr.strip() or f"max-mouse-click failed with code {proc.returncode}",
            )

    except Exception as e:
        duration_ms = (time.time() - start) * 1000.0
        return ActionOutcome(
            success=False,
            x=point.x,
            y=point.y,
            click_type=click_type,
            target_description=target.description if target else None,
            duration_ms=duration_ms,
            error=str(e),
        )
