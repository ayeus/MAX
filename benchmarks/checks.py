"""Independent observers of real macOS state for the benchmark suite.

These deliberately do NOT reuse MAX's capability or verification code, so a
benchmark verdict never depends on the system under test grading itself.
(Brightness is the one exception: DisplayServices is the only readout.)
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

SANDBOX = Path("/tmp/max-bench")


def sh(cmd: str, timeout: float = 10.0) -> str:
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def osa(script: str, timeout: float = 10.0) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


# --- applications -----------------------------------------------------------

def app_running(bundle_id: str) -> bool:
    return osa(f'application id "{bundle_id}" is running') == "true"


def frontmost_bundle() -> str:
    asn = sh("lsappinfo front")
    return sh(f"lsappinfo info -only bundleid {asn}").split("=")[-1].strip().strip('"')


def quit_app(bundle_id: str) -> None:
    if app_running(bundle_id):
        osa(f'tell application id "{bundle_id}" to quit')
        wait_until(lambda: not app_running(bundle_id), 5)


def launch_app(bundle_id: str) -> None:
    sh(f"open -b {bundle_id}")
    wait_until(lambda: app_running(bundle_id), 5)


def wait_until(pred, timeout: float, interval: float = 0.2) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# --- system settings --------------------------------------------------------

def output_volume() -> int:
    return int(osa("output volume of (get volume settings)"))


def output_muted() -> bool:
    return osa("output muted of (get volume settings)") == "true"


def set_output_volume(v: int, muted: bool = False) -> None:
    osa(f"set volume output volume {v}")
    osa(f"set volume output muted {'true' if muted else 'false'}")


def brightness() -> float | None:
    from macos.brightness import get_display_brightness
    ok, level, _ = get_display_brightness()
    return level if ok else None


def set_brightness(level: float) -> None:
    from macos.brightness import set_display_brightness
    set_display_brightness(level)


def clipboard() -> str:
    return sh("pbpaste")


# --- TextEdit / Notes -------------------------------------------------------

def textedit_reset() -> None:
    if app_running("com.apple.TextEdit"):
        osa('tell application "TextEdit" to close every document saving no')
        quit_app("com.apple.TextEdit")


def textedit_all_text() -> str:
    if not app_running("com.apple.TextEdit"):
        return ""
    return osa('tell application "TextEdit" to get text of every document as string')


def note_body(title: str) -> str | None:
    out = osa(
        f'tell application "Notes" to if (exists note "{title}") then get plaintext of note "{title}"'
    )
    return out or None


def delete_notes(title: str) -> None:
    osa(f'tell application "Notes" to delete (every note whose name is "{title}")')


# --- browsers ---------------------------------------------------------------

_BROWSERS = {"com.apple.Safari": "Safari", "com.google.Chrome": "Google Chrome"}


def browser_urls() -> list[str]:
    """URLs of every open tab in Safari and Chrome (if running)."""
    urls: list[str] = []
    for bid, name in _BROWSERS.items():
        if not app_running(bid):
            continue
        out = osa(f'tell application "{name}" to get URL of every tab of every window')
        urls += [u.strip() for u in out.split(",") if u.strip()]
    return urls


def any_url_contains(*needles: str) -> bool:
    return any(all(n in u for n in needles) for u in browser_urls())


def safari_open(url: str) -> None:
    osa(f'tell application "Safari" to open location "{url}"')
    wait_until(lambda: any_url_contains(url.split("//")[-1].rstrip("/")), 8)
    time.sleep(1.0)


# --- files / processes ------------------------------------------------------

def reset_sandbox() -> None:
    shutil.rmtree(SANDBOX, ignore_errors=True)
    SANDBOX.mkdir(parents=True)


def port_listening(port: int) -> bool:
    return bool(sh(f"lsof -nP -iTCP:{port} -sTCP:LISTEN -t"))


def kill_port(port: int) -> None:
    pids = sh(f"lsof -nP -iTCP:{port} -sTCP:LISTEN -t").split()
    for pid in pids:
        sh(f"kill {pid}")
