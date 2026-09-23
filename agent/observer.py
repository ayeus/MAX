"""First-class environment observer for MAX.

Captures real operating system state, active application, current directory,
and running processes before and after actions. Never fabricates state.
Consumes rich ComputerState and produces task-relevant compact projections.
"""

import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field

from capabilities.accessibility.models import ComputerState
from macos.applescript import run_applescript
from macos.shell import run_shell_command


from enum import Enum


class ObservationTier(str, Enum):
    FAST = "FAST"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class EnvironmentObservation(BaseModel):
    current_directory: str
    active_application: str
    active_window: str = ""
    recent_processes: list[str] = Field(default_factory=list)
    clipboard_preview: Optional[str] = None
    ui_summary: Optional[dict[str, Any]] = None
    interactive_elements_count: int = 0
    computer_state: Optional[ComputerState] = None
    display_brightness: Optional[float] = None
    tier: ObservationTier = ObservationTier.STANDARD


# Alias for backward and forward compatibility
AgentObservation = EnvironmentObservation


class Observer:
    """Inspects the computer state before and after actions across FAST, STANDARD, and DEEP tiers."""

    def __init__(self):
        self.last_computer_state: Optional[ComputerState] = None

    def get_active_application(self) -> str:
        """Query the frontmost macOS application name via fast lsappinfo, falling back to AppleScript."""
        try:
            res = run_shell_command("/usr/bin/lsappinfo info -only name $(/usr/bin/lsappinfo front)", timeout=1)
            if res.success and res.stdout.strip():
                out = res.stdout.strip()
                if "=" in out:
                    val = out.split("=", 1)[1].strip().strip('"')
                    if val:
                        return val
        except Exception:
            pass

        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        res = run_applescript(script, timeout=3)
        if res.success and res.stdout:
            return res.stdout.strip()
        return "Unknown"

    def get_current_directory(self) -> str:
        """Get the current working directory."""
        return str(Path.cwd().resolve())

    def get_running_process_sample(self, limit: int = 20) -> list[str]:
        """Get a sample of currently running application and process names."""
        res = run_shell_command("/bin/ps -A -o comm=", timeout=3)
        if res.success:
            names = []
            for line in res.stdout.splitlines():
                base = os.path.basename(line.strip())
                if base and base not in names:
                    names.append(base)
            return names[:limit]
        return []

    def get_clipboard_preview(self, max_chars: int = 100) -> Optional[str]:
        """Get short preview of current clipboard text."""
        res = run_shell_command("/usr/bin/pbpaste", timeout=2)
        if res.success and res.stdout.strip():
            txt = res.stdout.strip()
            return txt[:max_chars] + ("..." if len(txt) > max_chars else "")
        return None

    def get_display_brightness_safe(self) -> Optional[float]:
        """Quickly query display brightness without raising errors."""
        try:
            from macos.brightness import get_display_brightness
            ok, val, _ = get_display_brightness()
            return val if ok else None
        except Exception:
            return None

    def observe(
        self,
        tier: ObservationTier = ObservationTier.STANDARD,
        fast: Optional[bool] = None,
        include_ui: Optional[bool] = None,
        force_refresh: bool = False,
    ) -> EnvironmentObservation:
        """Perform tiered observation of current computer state.

        Tiers:
        - FAST: minimal context (active application, directory, brightness) for trivial actions (<30ms).
        - STANDARD: active application, active window, and visible interactive controls (~100ms).
        - DEEP: full recursive accessibility tree, complete process list, and clipboard preview (~300ms).

        Maintains backward compatibility with boolean `fast` and `include_ui` arguments.
        """
        # Resolve legacy flags into explicit tiers
        if fast is True and (include_ui is False or include_ui is None):
            active_tier = ObservationTier.FAST
        elif fast is False and include_ui is True and force_refresh:
            active_tier = ObservationTier.DEEP
        elif fast is False and include_ui is False:
            active_tier = ObservationTier.STANDARD
        else:
            active_tier = tier

        active_app = self.get_active_application()
        active_win = ""
        ui_sum = None
        count = 0
        state = None
        processes = []
        clip = None
        brightness = self.get_display_brightness_safe()

        if active_tier == ObservationTier.FAST:
            # Minimal observation for simple/system commands
            return EnvironmentObservation(
                current_directory=self.get_current_directory(),
                active_application=active_app,
                active_window="",
                recent_processes=[],
                clipboard_preview=None,
                ui_summary=None,
                interactive_elements_count=0,
                computer_state=None,
                display_brightness=brightness,
                tier=ObservationTier.FAST,
            )

        elif active_tier == ObservationTier.STANDARD:
            # Standard observation for interactive actions
            try:
                from capabilities.accessibility.tree import tree_extractor
                state = tree_extractor.get_computer_state(force_refresh=force_refresh)
                self.last_computer_state = state
                if state.active_application and state.active_application != "Unknown":
                    active_app = state.active_application
                active_win = state.active_window_title
                ui_sum = state.to_compact_prompt_summary()
                count = len(state.interactive_elements)
            except Exception:
                pass

            clip = self.get_clipboard_preview()
            return EnvironmentObservation(
                current_directory=self.get_current_directory(),
                active_application=active_app,
                active_window=active_win,
                recent_processes=[],
                clipboard_preview=clip,
                ui_summary=ui_sum,
                interactive_elements_count=count,
                computer_state=state,
                display_brightness=brightness,
                tier=ObservationTier.STANDARD,
            )

        else:  # DEEP
            # Comprehensive observation for ambiguous state, multi-step planning, and verification
            try:
                from capabilities.accessibility.tree import tree_extractor
                state = tree_extractor.get_computer_state(force_refresh=True)
                self.last_computer_state = state
                if state.active_application and state.active_application != "Unknown":
                    active_app = state.active_application
                active_win = state.active_window_title
                ui_sum = state.to_compact_prompt_summary()
                count = len(state.interactive_elements)
            except Exception:
                pass

            processes = self.get_running_process_sample()
            clip = self.get_clipboard_preview()
            return EnvironmentObservation(
                current_directory=self.get_current_directory(),
                active_application=active_app,
                active_window=active_win,
                recent_processes=processes,
                clipboard_preview=clip,
                ui_summary=ui_sum,
                interactive_elements_count=count,
                computer_state=state,
                display_brightness=brightness,
                tier=ObservationTier.DEEP,
            )



observer = Observer()
