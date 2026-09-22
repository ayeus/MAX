"""AppleScript automation executor for macOS."""

from pydantic import BaseModel
import subprocess
import time


class AppleScriptResult(BaseModel):
    script: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    permission_denied: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0


def escape_applescript_string(value: str) -> str:
    """Safely escape arbitrary text for insertion into AppleScript string literals.

    Prevents AppleScript injection by escaping backslashes and quotes.
    """
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")


def run_applescript(script: str, timeout: int = 15) -> AppleScriptResult:
    """Execute an AppleScript snippet via /usr/bin/osascript."""
    start_time = time.time()
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = (time.time() - start_time) * 1000.0
        stderr = proc.stderr.strip()
        permission_denied = "-1728" in stderr or "-1743" in stderr

        return AppleScriptResult(
            script=script,
            exit_code=proc.returncode,
            stdout=proc.stdout.strip(),
            stderr=stderr,
            duration_ms=duration_ms,
            permission_denied=permission_denied,
        )
    except subprocess.TimeoutExpired:
        duration_ms = (time.time() - start_time) * 1000.0
        return AppleScriptResult(
            script=script,
            exit_code=-1,
            stdout="",
            stderr=f"AppleScript timed out after {timeout} seconds.",
            duration_ms=duration_ms,
            permission_denied=False,
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        return AppleScriptResult(
            script=script,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration_ms,
            permission_denied=False,
        )
