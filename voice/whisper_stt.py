"""Speech-to-Text integration for MAX using Whisper."""

from pathlib import Path
from pydantic import BaseModel
import shutil
import subprocess
from macos.shell import run_shell_command


class TranscriptionResult(BaseModel):
    success: bool
    text: str
    duration_ms: float = 0.0
    model: str = "whisper"
    error: str | None = None


def is_whisper_available() -> bool:
    """Check if Whisper CLI or library is present."""
    if shutil.which("whisper"):
        return True
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_audio(wav_path: str | Path, model_name: str = "base") -> TranscriptionResult:
    """Transcribe an audio file using local Whisper."""
    p = Path(wav_path)
    if not p.exists():
        return TranscriptionResult(
            success=False,
            text="",
            error=f"Audio file '{wav_path}' does not exist.",
        )

    # Check CLI first
    whisper_bin = shutil.which("whisper")
    if whisper_bin:
        import time
        start = time.time()
        res = run_shell_command(
            f"{whisper_bin} '{p}' --model {model_name} --output_format txt --output_dir '{p.parent}'",
            timeout=45,
        )
        duration_ms = (time.time() - start) * 1000.0
        txt_file = p.with_suffix(".txt")
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8").strip()
            txt_file.unlink()
            return TranscriptionResult(
                success=True,
                text=text,
                duration_ms=duration_ms,
                model=model_name,
            )
        return TranscriptionResult(
            success=False,
            text="",
            duration_ms=duration_ms,
            error=res.stderr or "Whisper did not generate transcription.",
        )

    # Check python package
    try:
        import whisper
        import time
        start = time.time()
        model = whisper.load_model(model_name)
        result = model.transcribe(str(p))
        duration_ms = (time.time() - start) * 1000.0
        return TranscriptionResult(
            success=True,
            text=result.get("text", "").strip(),
            duration_ms=duration_ms,
            model=model_name,
        )
    except ImportError:
        return TranscriptionResult(
            success=False,
            text="",
            error=(
                "Whisper is not currently installed. To enable local voice STT, run: "
                "pip install openai-whisper"
            ),
        )
    except Exception as e:
        return TranscriptionResult(
            success=False,
            text="",
            error=f"Whisper transcription failed: {e}",
        )
