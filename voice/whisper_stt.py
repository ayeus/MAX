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


import wave
import numpy as np


def load_audio_waveform(wav_path: Path) -> np.ndarray:
    """Load a WAV audio file directly as a normalized float32 numpy array sampled at 16kHz."""
    with wave.open(str(wav_path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw_bytes = wf.readframes(n_frames)

    if sampwidth == 2:
        audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        audio = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported sample width: {sampwidth}")

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    if framerate != 16000:
        try:
            from scipy import signal
            num_samples = int(len(audio) * 16000 / framerate)
            audio = signal.resample(audio, num_samples)
        except Exception:
            pass

    return audio


import threading
from typing import Any, Optional


class STTService:
    """Manages warm in-memory instances of Whisper models to eliminate cold-load latency."""

    _models: dict[str, Any] = {}
    _lock = threading.Lock()

    @classmethod
    def get_model(cls, model_name: str = "base.en") -> Any:
        with cls._lock:
            if model_name not in cls._models:
                import whisper
                cls._models[model_name] = whisper.load_model(model_name)
            return cls._models[model_name]

    @classmethod
    def preload(cls, model_names: Optional[list[str]] = None) -> None:
        """Preload models at assistant startup."""
        names = model_names or ["base.en", "tiny.en"]
        for m in names:
            try:
                cls.get_model(m)
            except Exception:
                pass

    @classmethod
    def is_warmed(cls, model_name: str = "base.en") -> bool:
        return model_name in cls._models


def transcribe_audio(
    wav_path: Optional[str | Path] = None,
    audio_waveform: Optional[np.ndarray] = None,
    model_name: str = "base.en",
) -> TranscriptionResult:
    """Transcribe an audio file or direct in-memory float32 waveform using warm local Whisper."""
    audio: Optional[np.ndarray] = audio_waveform

    if audio is None:
        if not wav_path:
            return TranscriptionResult(
                success=False,
                text="",
                error="Neither wav_path nor audio_waveform was provided.",
            )
        p = Path(wav_path)
        if not p.exists():
            return TranscriptionResult(
                success=False,
                text="",
                error=f"Audio file '{wav_path}' does not exist.",
            )
        try:
            audio = load_audio_waveform(p)
        except Exception as e:
            return TranscriptionResult(
                success=False,
                text="",
                error=f"Failed to load audio waveform: {e}",
            )

    # 1. Use warm in-memory Whisper instance (zero reload latency)
    try:
        import time
        start = time.time()
        model = STTService.get_model(model_name)
        result = model.transcribe(audio, fp16=False)
        duration_ms = (time.time() - start) * 1000.0
        return TranscriptionResult(
            success=True,
            text=result.get("text", "").strip(),
            duration_ms=duration_ms,
            model=model_name,
        )
    except ImportError:
        pass
    except Exception as e:
        pass

    # 2. Check CLI fallback if ffmpeg is present
    whisper_bin = shutil.which("whisper")
    if whisper_bin and shutil.which("ffmpeg"):
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

    return TranscriptionResult(
        success=False,
        text="",
        error=(
            "Whisper is not currently installed or failed to initialize. "
            "To enable local voice STT, run: pip install openai-whisper"
        ),
    )

