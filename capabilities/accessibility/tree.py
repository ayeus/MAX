"""Accessibility tree extractor for macOS applications using native ApplicationServices and fallback APIs."""

from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Optional

from capabilities.accessibility.models import (
    AccessibilityHealthStatus,
    ComputerState,
    ObservationMetadata,
    UIElement,
    WindowState,
)
from capabilities.accessibility.native_backend import (
    extract_native_accessibility,
    is_native_available,
    parse_native_output_to_computer_state,
)
from macos.applescript import escape_applescript_string, run_applescript

logger = logging.getLogger(__name__)


class AccessibilityTreeExtractor:
    """Extracts structured, bounded semantic UI element trees from macOS applications.

    Production Authoritative Path:
        macOS ApplicationServices via native Swift binary (bin/max-ax-dump)
    Secondary Degraded Fallback:
        macOS System Events via AppleScript (used only if native binary is unavailable)
    """

    def __init__(
        self,
        max_depth: int = 6,
        max_elements: int = 100,
        timeout_ms: float = 1500.0,
        max_children: int = 50,
        cache_ttl: float = 0.5,
    ):
        self.max_depth = max_depth
        self.max_elements = max_elements
        self.timeout_ms = timeout_ms
        self.max_children = max_children
        self.cache_ttl = cache_ttl

        self._cached_state: Optional[ComputerState] = None
        self._cached_target_app: Optional[str] = None
        self._cache_time: float = 0.0

    def invalidate_cache(self) -> None:
        """Explicitly invalidate cached computer state (e.g. after mouse click or keystroke)."""
        self._cached_state = None
        self._cached_target_app = None
        self._cache_time = 0.0

    def _get_frontmost_app_info(self) -> tuple[str, Optional[int]]:
        """Fast query of current frontmost application name and PID to prevent cross-app cache contamination."""
        try:
            from macos.shell import run_shell_command
            res = run_shell_command("/usr/bin/lsappinfo info -only name,pid $(/usr/bin/lsappinfo front)", timeout=1)
            if res.success and res.stdout.strip():
                name = ""
                pid = None
                for line in res.stdout.strip().splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip().strip('"').lower()
                        v = v.strip().strip('"')
                        if "name" in k:
                            name = v.lower()
                        elif "pid" in k:
                            try:
                                pid = int(v)
                            except ValueError:
                                pass
                return name, pid
        except Exception:
            pass
        return "", None

    def get_computer_state(
        self,
        application_name: Optional[str] = None,
        force_refresh: bool = False,
    ) -> ComputerState:
        """Extract structured ComputerState for the specified or frontmost application.

        Uses the high-speed native ApplicationServices backend as the authoritative source.
        """
        now = time.time()
        if application_name and application_name.strip():
            cache_key = f"explicit:{application_name.strip().lower()}"
        else:
            front_name, front_pid = self._get_frontmost_app_info()
            cache_key = f"front:{front_name}:{front_pid}" if front_name else "front:default"

        # Check short-lived cache
        if (
            not force_refresh
            and self._cached_state is not None
            and (now - self._cache_time) < self.cache_ttl
            and self._cached_target_app == cache_key
        ):
            return self._cached_state

        state: Optional[ComputerState] = None

        # 1. Primary Authoritative Path: Native Swift ApplicationServices
        if is_native_available():
            try:
                native_data = extract_native_accessibility(
                    app_name=application_name,
                    max_depth=self.max_depth,
                    max_elements=self.max_elements,
                    timeout_ms=self.timeout_ms,
                    max_children=self.max_children,
                )
                status_str = native_data.get("status", "")
                if status_str in (
                    AccessibilityHealthStatus.ACCESSIBILITY_AVAILABLE.value,
                    AccessibilityHealthStatus.ACCESSIBILITY_DENIED.value,
                    AccessibilityHealthStatus.PARTIAL.value,
                ):
                    state = parse_native_output_to_computer_state(native_data)
                elif status_str == AccessibilityHealthStatus.ACCESSIBILITY_UNAVAILABLE.value and "permission" in str(native_data.get("error", "")).lower():
                    state = parse_native_output_to_computer_state(native_data)
            except Exception as e:
                logger.error("Error invoking native accessibility backend: %s", e)
                state = None

        # 2. Secondary Fallback Path: System Events AppleScript
        if state is None:
            logger.info("Falling back to secondary AppleScript accessibility extraction...")
            state = self._extract_applescript_fallback(application_name)

        # Cache result
        self._cached_state = state
        self._cached_target_app = cache_key
        self._cache_time = now

        return state

    def _extract_applescript_fallback(self, application_name: Optional[str] = None) -> ComputerState:
        """Secondary fallback using System Events AppleScript."""
        start_time = time.time()
        app_clause = ""
        if application_name and application_name.strip():
            clean_app = escape_applescript_string(application_name.strip())
            app_clause = f'set targetProc to first process whose name is "{clean_app}" or name contains "{clean_app}"'
        else:
            app_clause = 'set targetProc to first process whose frontmost is true'

        script = f"""
        tell application "System Events"
            try
                {app_clause}
                set procName to name of targetProc
                set winTitle to ""
                set winPos to {{0, 0}}
                set winSize to {{0, 0}}
                set allWins to {{}}

                try
                    set allWins to name of every window of targetProc
                end try

                set hasWin to false
                if (count of windows of targetProc) > 0 then
                    set targetWin to window 1 of targetProc
                    set hasWin to true
                    try
                        set winTitle to name of targetWin
                    end try
                    try
                        set winPos to position of targetWin
                        set winSize to size of targetWin
                    end try
                end if

                set elemList to {{}}
                if hasWin then
                    set targetRoles to {{"AXButton", "AXTextField", "AXTextArea", "AXSearchField", "AXPopUpButton", "AXCheckBox", "AXRadioButton", "AXTabGroup", "AXStaticText", "AXLink"}}
                    try
                        set topElems to every UI element of targetWin
                        repeat with el in topElems
                            try
                                set r to role of el
                                if r is in targetRoles then
                                    set n to ""
                                    set v to ""
                                    set d to ""
                                    set f to false
                                    try
                                        set n to name of el
                                    end try
                                    try
                                        set v to (value of el) as string
                                    end try
                                    try
                                        set d to description of el
                                    end try
                                    try
                                        set f to (focused of el)
                                    end try
                                    if (n is "missing value") then set n to ""
                                    if (v is "missing value") then set v to ""
                                    if (d is "missing value") then set d to ""
                                    if (n is not "") or (v is not "") or (d is not "") or (r is "AXTextField") or (r is "AXTextArea") then
                                        set end of elemList to (r & "|||" & n & "|||" & v & "|||" & d & "|||" & (f as string))
                                    end if
                                end if
                                if (count of elemList) >= {self.max_elements} then exit repeat
                            end try
                        end repeat
                    end try
                end if

                set outStr to procName & "###" & winTitle & "###" & (winPos as string) & "###" & (winSize as string) & "###"
                repeat with itm in elemList
                    set outStr to outStr & itm & "%%%"
                end repeat
                return outStr
            on error errMsg
                return "ERROR###" & errMsg
            end try
        end tell
        """

        res = run_applescript(script, timeout=int(self.timeout_ms / 1000.0) + 2)
        latency_ms = (time.time() - start_time) * 1000.0

        if not res.success or not res.stdout.strip() or res.stdout.strip().startswith("ERROR###"):
            err_msg = res.stdout.strip() if res.stdout.strip().startswith("ERROR###") else res.stderr
            status = AccessibilityHealthStatus.ACCESSIBILITY_DENIED if ("not allowed" in str(err_msg).lower() or "assistive" in str(err_msg).lower()) else AccessibilityHealthStatus.PARTIAL
            app_name = application_name or "Unknown"
            return ComputerState(
                active_application=app_name,
                active_window_title="",
                interactive_elements=[],
                observation_metadata=ObservationMetadata(
                    latency_ms=latency_ms,
                    accessibility_status=status,
                    backend="applescript_fallback",
                    error=err_msg or "AppleScript accessibility query failed",
                ),
            )

        parts = res.stdout.strip().split("###")
        proc_name = parts[0].strip() if len(parts) > 0 else (application_name or "Unknown")
        win_title = parts[1].strip() if len(parts) > 1 else ""
        pos_raw = parts[2].strip() if len(parts) > 2 else ""
        size_raw = parts[3].strip() if len(parts) > 3 else ""
        elems_block = parts[4].strip() if len(parts) > 4 else ""

        bounds = None
        try:
            p_parts = [float(x.strip()) for x in pos_raw.split(",") if x.strip()]
            s_parts = [float(x.strip()) for x in size_raw.split(",") if x.strip()]
            if len(p_parts) >= 2 and len(s_parts) >= 2:
                bounds = {"x": p_parts[0], "y": p_parts[1], "width": s_parts[0], "height": s_parts[1]}
        except Exception:
            pass

        elements: list[UIElement] = []
        focused_el: Optional[UIElement] = None

        if elems_block:
            for idx, item in enumerate(elems_block.split("%%%")):
                if not item.strip():
                    continue
                fields = item.split("|||")
                if len(fields) >= 4:
                    role = fields[0].strip()
                    title = fields[1].strip()
                    value = fields[2].strip() if fields[2].strip() else None
                    desc = fields[3].strip() if fields[3].strip() else None
                    is_focused = (fields[4].strip().lower() == "true") if len(fields) >= 5 else False

                    el = UIElement(
                        role=role,
                        title=title,
                        value=value,
                        description=desc,
                        is_focused=is_focused,
                        actions=["AXPress"] if "Button" in role else [],
                        path=f"AXWindow[0]/{role}[{idx}]",
                    )
                    elements.append(el)
                    if is_focused and not focused_el:
                        focused_el = el

        win_state = WindowState(
            title=win_title,
            role="AXWindow",
            is_focused=True,
            bounds=bounds,
        )

        return ComputerState(
            active_application=proc_name,
            active_window_title=win_title,
            active_window_bounds=bounds,
            active_window=win_state,
            windows=[win_state] if win_title or bounds else [],
            visible_windows=[win_title] if win_title else [],
            focused_element=focused_el,
            interactive_elements=elements,
            observation_metadata=ObservationMetadata(
                latency_ms=latency_ms,
                accessibility_status=AccessibilityHealthStatus.PARTIAL,
                backend="applescript_fallback",
                traversal_stats={"interactive_nodes_count": len(elements)},
            ),
        )


tree_extractor = AccessibilityTreeExtractor()
