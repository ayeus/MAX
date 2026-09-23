"""macOS system integration helpers."""

from .shell import run_shell_command, ShellResult
from .applescript import run_applescript, AppleScriptResult, escape_applescript_string
from .brightness import is_brightness_supported, get_display_brightness, set_display_brightness

__all__ = [
    "run_shell_command",
    "ShellResult",
    "run_applescript",
    "AppleScriptResult",
    "escape_applescript_string",
    "is_brightness_supported",
    "get_display_brightness",
    "set_display_brightness",
]

