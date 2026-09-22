"""macOS native Text-to-Speech synthesis and audio cues for MAX."""

import os
from pathlib import Path
from pydantic import BaseModel
import subprocess
import threading
import time
from typing import Optional
from macos.shell import run_shell_command


class VoiceInfo(BaseModel):
    name: str
    locale: str
    sample_text: str


class TTSResult(BaseModel):
    success: bool
    text: str
    voice: str | None = None
    duration_ms: float = 0.0
    error: str | None = None


_active_say_lock = threading.Lock()
_active_say_proc: Optional[subprocess.Popen] = None


def list_available_voices() -> list[VoiceInfo]:
    """Query all installed speech voices available in macOS."""
    res = run_shell_command("/usr/bin/say -v '?'", timeout=4)
    voices = []
    for line in res.stdout.splitlines():
        parts = line.split("#")
        header = parts[0].strip().split()
        if len(header) >= 2:
            name = header[0]
            locale = header[1]
            sample = parts[1].strip() if len(parts) > 1 else ""
            voices.append(VoiceInfo(name=name, locale=locale, sample_text=sample))
    return voices


def stop_speaking() -> None:
    """Immediately stop any active speech synthesis subprocess (used for cancellation)."""
    global _active_say_proc
    with _active_say_lock:
        if _active_say_proc is not None:
            try:
                _active_say_proc.terminate()
                _active_say_proc.wait(timeout=0.5)
            except Exception:
                try:
                    _active_say_proc.kill()
                except Exception:
                    pass
            finally:
                _active_say_proc = None


def speak_text(text: str, voice: str | None = None, rate: int | None = None) -> TTSResult:
    """Speak text using macOS native /usr/bin/say synchronously."""
    global _active_say_proc
    clean_text = text.strip()
    if not clean_text:
        return TTSResult(success=True, text="", duration_ms=0.0)

    cmd = ["/usr/bin/say"]
    if voice:
        cmd.extend(["-v", voice])
    if rate:
        cmd.extend(["-r", str(rate)])
    cmd.append(clean_text)

    start = time.time()
    try:
        with _active_say_lock:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            _active_say_proc = proc

        stdout, stderr = proc.communicate(timeout=30)
        duration_ms = (time.time() - start) * 1000.0

        with _active_say_lock:
            if _active_say_proc is proc:
                _active_say_proc = None

        return TTSResult(
            success=proc.returncode == 0,
            text=clean_text,
            voice=voice,
            duration_ms=duration_ms,
            error=stderr if proc.returncode != 0 else None,
        )
    except Exception as e:
        duration_ms = (time.time() - start) * 1000.0
        with _active_say_lock:
            _active_say_proc = None
        return TTSResult(
            success=False,
            text=clean_text,
            voice=voice,
            duration_ms=duration_ms,
            error=str(e),
        )


def speak_async(text: str, voice: str | None = None, rate: int | None = None) -> threading.Thread:
    """Speak text asynchronously in a background daemon thread."""
    t = threading.Thread(
        target=speak_text,
        args=(text, voice, rate),
        name="tts-worker",
        daemon=True,
    )
    t.start()
    return t


def play_earcon(sound_path: str = "/System/Library/Sounds/Tink.aiff") -> bool:
    """Play a non-blocking audio earcon cue.

    Verifies that the sound file exists before attempting playback.
    Provides graceful fallback (terminal bell or silent) if unavailable.
    """
    p = Path(sound_path)
    if not p.exists():
        # Fallback to standard system bell or silent
        try:
            print("\a", end="", flush=True)
        except Exception:
            pass
        return False

    try:
        # Launch afplay non-blocking
        subprocess.Popen(
            ["/usr/bin/afplay", "-v", "0.6", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
