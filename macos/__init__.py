"""macOS system integration helpers."""

from .shell import run_shell_command, ShellResult
from .applescript import run_applescript, AppleScriptResult

__all__ = [
    "run_shell_command",
    "ShellResult",
    "run_applescript",
    "AppleScriptResult",
]
