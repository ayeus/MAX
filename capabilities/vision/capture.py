"""Screen capture and multi-monitor display inspection for MAX."""

from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel, Field
import re
import subprocess
import tempfile
import time
from macos.shell import run_shell_command
from security.permissions import check_screen_recording_permission, PermissionStatus


class DisplayInfo(BaseModel):
    display_id: int = 1
    name: str = "Main Display"
    is_main: bool = True
    pixel_width: int = 2560
    pixel_height: int = 1600
    point_width: float = 1280.0
    point_height: float = 800.0
    scale_factor: float = 2.0


class CaptureResult(BaseModel):
    success: bool
    image_path: str
    display: DisplayInfo
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0
    error: str | None = None

    def cleanup(self) -> None:
        """Discard temporary screenshot file securely."""
        if self.image_path:
            p = Path(self.image_path)
            if p.exists() and "tmp" in str(p):
                try:
                    p.unlink()
                except Exception:
                    pass


def get_connected_displays() -> list[DisplayInfo]:
    """Query connected displays, resolutions, and coordinate scale factors from macOS."""
    # 1. Query point bounds from Finder desktop
    bounds_res = run_shell_command(
        "/usr/bin/osascript -e 'tell application \"Finder\" to get bounds of window of desktop'",
        timeout=3,
    )
    point_w, point_h = 1440.0, 900.0
    if bounds_res.success and bounds_res.stdout.strip():
        parts = [p.strip() for p in bounds_res.stdout.split(",") if p.strip()]
        if len(parts) >= 4:
            try:
                x1, y1, x2, y2 = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
                point_w = max(100.0, x2 - x1)
                point_h = max(100.0, y2 - y1)
            except ValueError:
                pass

    # 2. Query pixel resolution from system_profiler
    prof_res = run_shell_command("/usr/sbin/system_profiler SPDisplaysDataType", timeout=4)
    pixel_w, pixel_h = int(point_w * 2), int(point_h * 2)
    disp_name = "Built-in Liquid Retina Display"

    if prof_res.success:
        res_match = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", prof_res.stdout)
        if res_match:
            pixel_w = int(res_match.group(1))
            pixel_h = int(res_match.group(2))
        name_match = re.search(r"Displays:\s*\n\s*([^:\n]+):", prof_res.stdout)
        if name_match:
            disp_name = name_match.group(1).strip()

    scale = round(pixel_w / point_w, 2) if point_w > 0 else 2.0

    return [
        DisplayInfo(
            display_id=1,
            name=disp_name,
            is_main=True,
            pixel_width=pixel_w,
            pixel_height=pixel_h,
            point_width=point_w,
            point_height=point_h,
            scale_factor=scale,
        )
    ]


def capture_screen(output_path: Path | str | None = None, display_id: int = 1) -> CaptureResult:
    """Capture a screenshot of the display to a temporary or specified PNG file."""
    # Check Screen Recording permission first
    perm = check_screen_recording_permission()
    if perm.status != PermissionStatus.GRANTED:
        return CaptureResult(
            success=False,
            image_path="",
            display=DisplayInfo(),
            error=(
                "Screen Recording permission is required for MAX vision.\n"
                "To enable it, open: System Settings > Privacy & Security > Screen Recording "
                "and grant access to your Terminal / IDE."
            ),
        )

    displays = get_connected_displays()
    selected_display = displays[0]
    for d in displays:
        if d.display_id == display_id:
            selected_display = d
            break

    if output_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="max_screen_")
        target_path = Path(tmp.name)
        tmp.close()
    else:
        target_path = Path(output_path)

    start = time.time()
    import shutil
    sc_bin = shutil.which("screencapture") or "/usr/sbin/screencapture"
    try:
        # -x: mute sound, -C: capture cursor
        proc = subprocess.run(
            [sc_bin, "-x", "-C", str(target_path)],
            capture_output=True,
            text=True,
            timeout=8,
        )
        duration_ms = (time.time() - start) * 1000.0

        if proc.returncode != 0 or not target_path.exists() or target_path.stat().st_size == 0:
            if target_path.exists():
                target_path.unlink()
            return CaptureResult(
                success=False,
                image_path="",
                display=selected_display,
                duration_ms=duration_ms,
                error=proc.stderr or "screencapture failed to create image file.",
            )

        # Inspect real pixel dimensions using sips
        dim_res = run_shell_command(
            f"/usr/bin/sips -g pixelWidth -g pixelHeight '{target_path}'",
            timeout=3,
        )
        if dim_res.success:
            w_match = re.search(r"pixelWidth:\s*(\d+)", dim_res.stdout)
            h_match = re.search(r"pixelHeight:\s*(\d+)", dim_res.stdout)
            if w_match and h_match:
                selected_display.pixel_width = int(w_match.group(1))
                selected_display.pixel_height = int(h_match.group(1))
                if selected_display.point_width > 0:
                    selected_display.scale_factor = round(
                        selected_display.pixel_width / selected_display.point_width, 2
                    )

        return CaptureResult(
            success=True,
            image_path=str(target_path),
            display=selected_display,
            duration_ms=duration_ms,
        )

    except Exception as e:
        duration_ms = (time.time() - start) * 1000.0
        if target_path.exists():
            target_path.unlink()
        return CaptureResult(
            success=False,
            image_path="",
            display=selected_display,
            duration_ms=duration_ms,
            error=str(e),
        )
