"""First-class environment observer for MAX.

Captures real operating system state, active application, current directory,
and running processes before and after actions. Never fabricates state.
"""

from pathlib import Path
from typing import Any
from pydantic import BaseModel
import os
from macos.applescript import run_applescript
from macos.shell import run_shell_command


class EnvironmentObservation(BaseModel):
    current_directory: str
    active_application: str
    active_window: str = ""
    recent_processes: list[str] = []
    clipboard_preview: str | None = None
    ui_summary: dict[str, Any] | None = None
    interactive_elements_count: int = 0


# Alias for backward and forward compatibility
AgentObservation = EnvironmentObservation


class Observer:
    """Inspects the computer state before and after actions."""

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

    def get_clipboard_preview(self, max_chars: int = 100) -> str | None:
        """Get short preview of current clipboard text."""
        res = run_shell_command("/usr/bin/pbpaste", timeout=2)
        if res.success and res.stdout.strip():
            txt = res.stdout.strip()
            return txt[:max_chars] + ("..." if len(txt) > max_chars else "")
        return None

    def observe(self, fast: bool = False, include_ui: bool = True) -> EnvironmentObservation:
        """Perform observation of current computer state.

        If include_ui=True, captures active window and interactive controls.
        If fast=True, avoids expensive full process tree queries.
        """
        active_app = self.get_active_application()
        active_win = ""
        ui_sum = None
        count = 0

        if include_ui:
            try:
                from capabilities.accessibility.tree import tree_extractor
                state = tree_extractor.get_computer_state()
                if state.active_application and state.active_application != "Unknown":
                    active_app = state.active_application
                active_win = state.active_window_title
                ui_sum = state.to_compact_prompt_summary()
                count = len(state.interactive_elements)
            except Exception:
                pass

        return EnvironmentObservation(
            current_directory=self.get_current_directory(),
            active_application=active_app,
            active_window=active_win,
            recent_processes=[] if fast else self.get_running_process_sample(),
            clipboard_preview=None if fast else self.get_clipboard_preview(),
            ui_summary=ui_sum,
            interactive_elements_count=count,
        )


observer = Observer()
