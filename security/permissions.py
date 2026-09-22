"""macOS TCC Permission detection and user guidance.

Tests real macOS permissions and reports true status. Never fabricates permissions.
Provides exact paths in macOS System Settings when permissions are missing.
"""

from enum import Enum
from pathlib import Path
from pydantic import BaseModel
import subprocess
import tempfile


class PermissionStatus(str, Enum):
    GRANTED = "GRANTED"
    DENIED_OR_MISSING = "DENIED_OR_MISSING"
    UNKNOWN = "UNKNOWN"


class PermissionReport(BaseModel):
    permission_name: str
    status: PermissionStatus
    description: str
    system_settings_path: str
    impact: str


def check_accessibility_permission() -> PermissionReport:
    """Test if the process currently possesses macOS Accessibility (Assistive Access) permission.

    Runs an AppleScript query that attempts to inspect UI elements of the frontmost process.
    Error -1728 specifically indicates lack of assistive access.
    """
    script = 'tell application "System Events" to tell (first process whose frontmost is true) to get name of windows'
    try:
        res = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return PermissionReport(
                permission_name="Accessibility",
                status=PermissionStatus.GRANTED,
                description="Permission to inspect and interact with UI elements across applications.",
                system_settings_path="System Settings > Privacy & Security > Accessibility",
                impact="Full semantic UI element tree inspection is available.",
            )
        else:
            return PermissionReport(
                permission_name="Accessibility",
                status=PermissionStatus.DENIED_OR_MISSING,
                description="Permission to inspect and interact with UI elements across applications.",
                system_settings_path="System Settings > Privacy & Security > Accessibility",
                impact="MAX will fall back to CLI, AppleScript commands, and application APIs instead of direct UI element tree inspection.",
            )
    except Exception:
        return PermissionReport(
            permission_name="Accessibility",
            status=PermissionStatus.UNKNOWN,
            description="Unable to verify Accessibility status.",
            system_settings_path="System Settings > Privacy & Security > Accessibility",
            impact="Assistive access could not be tested.",
        )


def check_screen_recording_permission() -> PermissionReport:
    """Test if the process possesses macOS Screen Recording permission.

    Tests via screencapture utility to a temporary scratch file.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    import shutil
    sc_bin = shutil.which("screencapture") or "/usr/sbin/screencapture"
    try:
        res = subprocess.run(
            [sc_bin, "-x", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        has_captured = res.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0
        if tmp_path.exists():
            tmp_path.unlink()

        if has_captured:
            return PermissionReport(
                permission_name="Screen Recording",
                status=PermissionStatus.GRANTED,
                description="Permission to capture display screenshots for visual fallback reasoning.",
                system_settings_path="System Settings > Privacy & Security > Screen Recording",
                impact="Vision fallback and visual screen inspection are available.",
            )
        else:
            return PermissionReport(
                permission_name="Screen Recording",
                status=PermissionStatus.DENIED_OR_MISSING,
                description="Permission to capture display screenshots for visual fallback reasoning.",
                system_settings_path="System Settings > Privacy & Security > Screen Recording",
                impact="Visual screenshot capture is disabled until granted in System Settings.",
            )
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        return PermissionReport(
            permission_name="Screen Recording",
            status=PermissionStatus.UNKNOWN,
            description="Unable to verify Screen Recording status.",
            system_settings_path="System Settings > Privacy & Security > Screen Recording",
            impact="Screen recording could not be tested.",
        )


def check_macos_permissions() -> list[PermissionReport]:
    """Inspect all relevant macOS security and privacy permissions."""
    return [
        check_accessibility_permission(),
        check_screen_recording_permission(),
    ]
