"""Audio recording driver for MAX on macOS."""

from pathlib import Path
from pydantic import BaseModel
import subprocess
import tempfile
import time


class AudioRecording(BaseModel):
    success: bool
    wav_path: str
    duration_seconds: float
    error: str | None = None


def record_microphone(duration_seconds: float = 4.0, output_wav: Path | None = None) -> AudioRecording:
    """Record audio from macOS default microphone into a 16kHz mono WAV file."""
    recorder_bin = Path(__file__).parent.parent / "bin/max-recorder"
    if not recorder_bin.exists():
        return AudioRecording(
            success=False,
            wav_path="",
            duration_seconds=0.0,
            error=f"Native audio recorder binary '{recorder_bin}' is missing.",
        )

    if output_wav is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        target_path = Path(tmp.name)
        tmp.close()
    else:
        target_path = output_wav

    try:
        proc = subprocess.run(
            [str(recorder_bin), str(target_path), str(duration_seconds)],
            capture_output=True,
            text=True,
            timeout=int(duration_seconds) + 5,
        )
        is_success = proc.returncode == 0 and target_path.exists() and target_path.stat().st_size > 0
        return AudioRecording(
            success=is_success,
            wav_path=str(target_path),
            duration_seconds=duration_seconds,
            error=proc.stderr if not is_success else None,
        )
    except Exception as e:
        return AudioRecording(
            success=False,
            wav_path=str(target_path),
            duration_seconds=0.0,
            error=str(e),
        )
