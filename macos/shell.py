"""Subprocess and shell execution for macOS."""

from pathlib import Path
from pydantic import BaseModel
import os
import subprocess
from app.config import settings


class ShellResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_shell_command(
    command: str,
    cwd: str | Path | None = None,
    timeout: int | None = None,
    env: dict | None = None,
) -> ShellResult:
    """Execute a shell command via /bin/zsh with real output capture and timeout."""
    import time

    start_time = time.time()
    work_dir = Path(cwd).resolve() if cwd else Path.cwd()
    cmd_timeout = timeout or settings.command_timeout_seconds

    # Inherit current environment and ensure standard PATH additions
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    # Ensure Homebrew and user paths are in PATH
    extra_paths = ["/opt/homebrew/bin", "/usr/local/bin", str(Path.home() / ".local/bin")]
    current_path = merged_env.get("PATH", "")
    for p in extra_paths:
        if p not in current_path:
            current_path = f"{p}:{current_path}"
    merged_env["PATH"] = current_path

    try:
        proc = subprocess.run(
            ["/bin/zsh", "-c", command],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=cmd_timeout,
            env=merged_env,
        )
        duration_ms = (time.time() - start_time) * 1000.0
        return ShellResult(
            command=command,
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as e:
        duration_ms = (time.time() - start_time) * 1000.0
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout=e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
            stderr=f"Command timed out after {cmd_timeout} seconds.",
            duration_ms=duration_ms,
            timed_out=True,
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000.0
        return ShellResult(
            command=command,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration_ms,
            timed_out=False,
        )
