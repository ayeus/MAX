"""Native macOS Accessibility Backend Bridge for MAX.

Integrates with bin/max-ax-dump (compiled Swift tool) using ApplicationServices
for zero-hallucination, high-performance recursive accessibility tree extraction.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Optional

from capabilities.accessibility.models import (
    AccessibilityHealthStatus,
    ComputerState,
    ObservationMetadata,
    UIElement,
    WindowState,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BIN_PATH = PROJECT_ROOT / "bin" / "max-ax-dump"
SWIFT_SOURCE = PROJECT_ROOT / "capabilities" / "accessibility" / "native_tree.swift"


def is_native_available() -> bool:
    """Check if native macOS accessibility binary can run on this system."""
    if sys.platform != "darwin":
        return False
    if BIN_PATH.exists() and os.access(BIN_PATH, os.X_OK):
        return True
    # If source exists, check if swiftc can compile it
    return SWIFT_SOURCE.exists()


def ensure_native_binary() -> Optional[Path]:
    """Ensure bin/max-ax-dump is built and up to date with Swift source."""
    if sys.platform != "darwin":
        return None

    if BIN_PATH.exists() and os.access(BIN_PATH, os.X_OK):
        # If source is newer than binary, recompile
        if SWIFT_SOURCE.exists() and SWIFT_SOURCE.stat().st_mtime > BIN_PATH.stat().st_mtime:
            logger.info("Swift source is newer than binary; recompiling bin/max-ax-dump...")
        else:
            return BIN_PATH

    if not SWIFT_SOURCE.exists():
        logger.warning("Swift source %s does not exist.", SWIFT_SOURCE)
        return None

    BIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    compile_cmd = ["/usr/bin/swiftc", "-O", "-o", str(BIN_PATH), str(SWIFT_SOURCE)]
    try:
        logger.info("Compiling native accessibility helper: %s", " ".join(compile_cmd))
        res = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and BIN_PATH.exists():
            os.chmod(BIN_PATH, 0o755)
            logger.info("Successfully compiled %s", BIN_PATH)
            return BIN_PATH
        else:
            logger.error("Failed to compile native accessibility helper: %s", res.stderr)
            return None
    except Exception as e:
        logger.error("Error invoking swiftc: %s", e)
        return None


def extract_native_accessibility(
    pid: Optional[int] = None,
    app_name: Optional[str] = None,
    max_depth: int = 6,
    max_elements: int = 100,
    timeout_ms: float = 1500.0,
    max_children: int = 50,
    active_window_only: bool = False,
) -> dict[str, Any]:
    """Execute bin/max-ax-dump and return structured dictionary response.

    Returns structured error dictionary if platform is unsupported or execution fails.
    """
    if sys.platform != "darwin":
        return {
            "status": AccessibilityHealthStatus.ACCESSIBILITY_UNAVAILABLE.value,
            "error": "Native macOS accessibility backend is only supported on Darwin (macOS).",
            "stats": {"duration_ms": 0.0},
        }

    binary = ensure_native_binary()
    if not binary:
        return {
            "status": AccessibilityHealthStatus.ACCESSIBILITY_UNAVAILABLE.value,
            "error": "Native accessibility binary bin/max-ax-dump is unavailable and could not be compiled.",
            "stats": {"duration_ms": 0.0},
        }

    cmd = [
        str(binary),
        "--max-depth", str(max_depth),
        "--max-elements", str(max_elements),
        "--timeout-ms", str(timeout_ms),
        "--max-children", str(max_children),
    ]
    if pid is not None:
        cmd.extend(["--pid", str(pid)])
    elif app_name and app_name.strip():
        cmd.extend(["--app", app_name.strip()])

    if active_window_only:
        cmd.append("--active-window-only")

    start_wall = time.time()
    wall_timeout = (timeout_ms / 1000.0) + 1.0

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=wall_timeout,
        )
        latency_ms = (time.time() - start_wall) * 1000.0

        if proc.returncode != 0 and not proc.stdout.strip():
            logger.error("Native accessibility binary exited with code %d: %s", proc.returncode, proc.stderr)
            return {
                "status": AccessibilityHealthStatus.PARTIAL.value,
                "error": proc.stderr.strip() or f"Process exited with code {proc.returncode}",
                "stats": {"duration_ms": latency_ms},
            }

        out_str = proc.stdout.strip()
        if not out_str:
            return {
                "status": AccessibilityHealthStatus.UNKNOWN.value,
                "error": "Empty response from accessibility binary.",
                "stats": {"duration_ms": latency_ms},
            }

        data = json.loads(out_str)
        if "stats" in data and isinstance(data["stats"], dict):
            data["stats"]["wall_latency_ms"] = latency_ms
        return data

    except subprocess.TimeoutExpired:
        latency_ms = (time.time() - start_wall) * 1000.0
        logger.warning("Native accessibility binary timed out after %.2fs", wall_timeout)
        return {
            "status": AccessibilityHealthStatus.PARTIAL.value,
            "error": f"Observation timed out after {timeout_ms}ms.",
            "stats": {"duration_ms": latency_ms, "truncated_by_budget": "timeout"},
        }
    except json.JSONDecodeError as je:
        latency_ms = (time.time() - start_wall) * 1000.0
        logger.error("Failed to parse JSON from native accessibility binary: %s", je)
        return {
            "status": AccessibilityHealthStatus.PARTIAL.value,
            "error": f"Malformed JSON from native accessibility binary: {je}",
            "stats": {"duration_ms": latency_ms},
        }
    except Exception as e:
        latency_ms = (time.time() - start_wall) * 1000.0
        logger.error("Unexpected error running native accessibility binary: %s", e)
        return {
            "status": AccessibilityHealthStatus.UNKNOWN.value,
            "error": str(e),
            "stats": {"duration_ms": latency_ms},
        }


def _build_ui_element_tree(node_dict: Optional[dict[str, Any]]) -> Optional[UIElement]:
    """Recursively convert raw dictionary node to typed UIElement."""
    if not node_dict or not isinstance(node_dict, dict):
        return None

    raw_children = node_dict.get("children", [])
    parsed_children: list[UIElement] = []
    if isinstance(raw_children, list):
        for c in raw_children:
            if isinstance(c, dict):
                child_el = _build_ui_element_tree(c)
                if child_el:
                    parsed_children.append(child_el)

    bounds = None
    if isinstance(node_dict.get("bounds"), dict):
        b = node_dict["bounds"]
        bounds = {
            "x": float(b.get("x", 0)),
            "y": float(b.get("y", 0)),
            "width": float(b.get("width", 0)),
            "height": float(b.get("height", 0)),
        }

    is_enabled = bool(node_dict["is_enabled"]) if node_dict.get("is_enabled") is not None else None
    is_selected = bool(node_dict["is_selected"]) if node_dict.get("is_selected") is not None else None

    return UIElement(
        role=str(node_dict.get("role", "AXUnknown")),
        subrole=node_dict.get("subrole"),
        title=str(node_dict.get("title", "")),
        value=str(node_dict["value"]) if node_dict.get("value") is not None else None,
        description=str(node_dict["description"]) if node_dict.get("description") is not None else None,
        identifier=str(node_dict["identifier"]) if node_dict.get("identifier") is not None else None,
        bounds=bounds,
        is_focused=bool(node_dict.get("is_focused", False)),
        is_enabled=is_enabled,
        is_selected=is_selected,
        actions=list(node_dict.get("actions", [])),
        path=str(node_dict.get("path", "")),
        parent_path=node_dict.get("parent_path"),
        children=parsed_children,
    )


def parse_native_output_to_computer_state(data: dict[str, Any]) -> ComputerState:
    """Transform raw dictionary from native binary into typed ComputerState."""
    status_str = data.get("status", AccessibilityHealthStatus.UNKNOWN.value)
    try:
        health_status = AccessibilityHealthStatus(status_str)
    except Exception:
        health_status = AccessibilityHealthStatus.UNKNOWN

    app_info = data.get("application", {})
    app_name = app_info.get("name", "Unknown") if isinstance(app_info, dict) else "Unknown"
    app_pid = app_info.get("pid") if isinstance(app_info, dict) else None

    # Parse windows
    windows: list[WindowState] = []
    raw_wins = data.get("windows", [])
    if isinstance(raw_wins, list):
        for w in raw_wins:
            if isinstance(w, dict):
                bounds = None
                if isinstance(w.get("bounds"), dict):
                    b = w["bounds"]
                    bounds = {
                        "x": float(b.get("x", 0)),
                        "y": float(b.get("y", 0)),
                        "width": float(b.get("width", 0)),
                        "height": float(b.get("height", 0)),
                    }
                windows.append(
                    WindowState(
                        title=str(w.get("title", "")),
                        role=str(w.get("role", "AXWindow")),
                        subrole=w.get("subrole"),
                        is_focused=bool(w.get("is_focused", False)),
                        is_minimized=bool(w.get("is_minimized", False)),
                        is_modal=bool(w.get("is_modal", False)),
                        bounds=bounds,
                        pid=w.get("pid"),
                    )
                )

    # Active window
    active_win_dict = data.get("active_window")
    active_window: Optional[WindowState] = None
    active_title = ""
    active_bounds = None
    if isinstance(active_win_dict, dict):
        if isinstance(active_win_dict.get("bounds"), dict):
            b = active_win_dict["bounds"]
            active_bounds = {
                "x": float(b.get("x", 0)),
                "y": float(b.get("y", 0)),
                "width": float(b.get("width", 0)),
                "height": float(b.get("height", 0)),
            }
        active_title = str(active_win_dict.get("title", ""))
        active_window = WindowState(
            title=active_title,
            role=str(active_win_dict.get("role", "AXWindow")),
            subrole=active_win_dict.get("subrole"),
            is_focused=bool(active_win_dict.get("is_focused", False)),
            is_minimized=bool(active_win_dict.get("is_minimized", False)),
            is_modal=bool(active_win_dict.get("is_modal", False)),
            bounds=active_bounds,
            pid=active_win_dict.get("pid"),
        )
    elif windows:
        # Fall back to first window
        active_window = windows[0]
        active_title = active_window.title
        active_bounds = active_window.bounds

    # Focused UI element
    raw_focused = data.get("focused_element")
    focused_element = _build_ui_element_tree(raw_focused) if raw_focused else None

    # Root tree
    raw_root = data.get("root_element")
    root_element = _build_ui_element_tree(raw_root) if raw_root else None

    # Flattened interactive controls
    interactive_elements: list[UIElement] = []
    raw_interactive = data.get("flattened_interactive", [])
    if isinstance(raw_interactive, list) and raw_interactive:
        for node in raw_interactive:
            if isinstance(node, dict):
                el = _build_ui_element_tree(node)
                if el:
                    interactive_elements.append(el)
    elif root_element:
        # If flattened_interactive wasn't explicitly populated, flatten root
        interactive_elements = root_element.flatten()

    # Observation metadata
    stats = data.get("stats", {}) if isinstance(data.get("stats"), dict) else {}
    is_truncated = bool(stats.get("is_truncated", False))
    truncated_by = stats.get("truncated_by_budget")

    if is_truncated and health_status == AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE:
        health_status = AccessibilityHealthStatus.PARTIAL

    metadata = ObservationMetadata(
        latency_ms=float(stats.get("duration_ms", 0.0)),
        accessibility_status=health_status,
        backend="native_swift",
        is_truncated=is_truncated,
        truncated_by=truncated_by,
        traversal_stats=stats,
        error=data.get("error"),
    )

    return ComputerState(
        active_application=app_name,
        active_application_pid=app_pid,
        active_window_title=active_title,
        active_window_bounds=active_bounds,
        active_window=active_window,
        windows=windows,
        visible_windows=[w.title for w in windows if w.title],
        focused_element=focused_element,
        root_element=root_element,
        interactive_elements=interactive_elements,
        observation_metadata=metadata,
    )
