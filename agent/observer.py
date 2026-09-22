"""First-class environment observer for MAX.

Captures real operating system state, active application, current directory,
and running processes before and after actions. Never fabricates state.
"""

from pathlib import Path
from pydantic import BaseModel
import os
from macos.applescript import run_applescript
from macos.shell import run_shell_command


class EnvironmentObservation(BaseModel):
    current_directory: str
    active_application: str
    recent_processes: list[str] = []
    clipboard_preview: str | None = None


class Observer:
    """Inspects the computer state before and after actions."""

    def get_active_application(self) -> str:
        """Query the frontmost macOS application name."""
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

    def observe(self) -> EnvironmentObservation:
        """Perform a comprehensive observation of current computer state."""
        return EnvironmentObservation(
            current_directory=self.get_current_directory(),
            active_application=self.get_active_application(),
            recent_processes=self.get_running_process_sample(),
            clipboard_preview=self.get_clipboard_preview(),
        )


observer = Observer()
