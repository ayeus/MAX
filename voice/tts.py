"""macOS native Text-to-Speech synthesis for MAX."""

from pydantic import BaseModel
import subprocess
import time
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


def speak_text(text: str, voice: str | None = None, rate: int | None = None) -> TTSResult:
    """Speak text using macOS native /usr/bin/say."""
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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        duration_ms = (time.time() - start) * 1000.0
        return TTSResult(
            success=proc.returncode == 0,
            text=clean_text,
            voice=voice,
            duration_ms=duration_ms,
            error=proc.stderr if proc.returncode != 0 else None,
        )
    except Exception as e:
        duration_ms = (time.time() - start) * 1000.0
        return TTSResult(
            success=False,
            text=clean_text,
            voice=voice,
            duration_ms=duration_ms,
            error=str(e),
        )
