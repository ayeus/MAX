"""High-performance continuous audio streaming bridge for MAX on macOS.

Consumes raw 16kHz 16-bit mono linear PCM from Swift max-audio-stream,
maintains a rolling circular pre-buffer (300-800ms) to ensure commands
beginning immediately after wake words are not clipped, and provides
real-time energy-based VAD for responsive utterance endpointing.
"""

from __future__ import annotations
import collections
import logging
import math
import numpy as np
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class ContinuousAudioStream:
    """Persistent audio streaming engine consuming native macOS AVAudioEngine."""

    SAMPLE_RATE = 16000
    BYTES_PER_SAMPLE = 2  # 16-bit linear PCM
    BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE  # 32,000 bytes/sec

    def __init__(self, pre_roll_ms: float = 600.0):
        self.pre_roll_ms = max(300.0, min(1000.0, pre_roll_ms))
        self.pre_roll_bytes = int((self.pre_roll_ms / 1000.0) * self.BYTES_PER_SECOND)
        self._ring_buffer = bytearray()
        self._buffer_lock = threading.Lock()

        self._proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_ready = False
        self._binary_path = Path(__file__).parent.parent / "bin/max-audio-stream"

        # VAD calibration
        self.noise_floor_db = -45.0
        self.speech_threshold_db = -32.0

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._stop_event.is_set()

    def start(self, timeout: float = 5.0) -> bool:
        """Start the background audio stream process and continuous ring-buffer worker."""
        if self.is_running:
            return True

        if not self._binary_path.exists():
            logger.warning(f"Audio stream binary '{self._binary_path}' not found. Compiling or using fallback.")
            return False

        self._stop_event.clear()
        try:
            self._proc = subprocess.Popen(
                [str(self._binary_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as e:
            logger.error(f"Failed to start max-audio-stream: {e}")
            return False

        # Wait for ready signal on stderr
        ready_event = threading.Event()

        def stderr_watcher():
            for line in iter(self._proc.stderr.readline, b""):
                text = line.decode("utf-8", errors="ignore").strip()
                if "AUDIO_STREAM_READY" in text:
                    self._is_ready = True
                    ready_event.set()
                elif "ERROR" in text:
                    logger.error(f"max-audio-stream error: {text}")

        watcher = threading.Thread(target=stderr_watcher, daemon=True)
        watcher.start()

        if not ready_event.wait(timeout=timeout):
            logger.warning("Audio stream ready signal timed out. Attempting read anyway.")

        self._reader_thread = threading.Thread(target=self._read_stream_loop, daemon=True)
        self._reader_thread.start()
        return True

    def _read_stream_loop(self) -> None:
        """Continuously read raw 16-bit PCM bytes into the pre-roll ring buffer."""
        chunk_size = 1024  # 512 samples = 32ms per read
        while not self._stop_event.is_set() and self._proc and self._proc.poll() is None:
            try:
                data = self._proc.stdout.read(chunk_size)
                if not data:
                    time.sleep(0.01)
                    continue

                with self._buffer_lock:
                    self._ring_buffer.extend(data)
                    # Keep ring buffer strictly bounded to pre_roll_bytes
                    if len(self._ring_buffer) > self.pre_roll_bytes:
                        del self._ring_buffer[: len(self._ring_buffer) - self.pre_roll_bytes]
            except Exception as e:
                logger.error(f"Audio stream read error: {e}")
                break

    def get_pre_roll_bytes(self) -> bytes:
        """Retrieve copy of current rolling pre-buffer audio bytes."""
        with self._buffer_lock:
            return bytes(self._ring_buffer)

    def calculate_rms_db(self, pcm_bytes: bytes) -> float:
        """Compute RMS audio power level in decibels relative to full scale."""
        if not pcm_bytes or len(pcm_bytes) < 2:
            return -100.0
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        rms = np.sqrt(np.mean(samples ** 2))
        if rms <= 1.0:
            return -100.0
        # 20 * log10(rms / 32768.0)
        db = 20.0 * math.log10(rms / 32768.0)
        return float(db)

    def capture_utterance(
        self,
        max_duration: float = 8.0,
        silence_timeout: float = 0.8,
        include_pre_roll: bool = True,
    ) -> Optional[np.ndarray]:
        """Capture spoken utterance using dynamic energy VAD, starting with pre-roll audio.

        Returns float32 normalized waveform [-1.0, 1.0] ready for in-memory Whisper STT.
        """
        if not self.is_running:
            return None

        # Prepend rolling pre-buffer audio so command beginning is retained
        captured = bytearray()
        if include_pre_roll:
            captured.extend(self.get_pre_roll_bytes())

        poll_chunk = 1024  # 32ms
        speech_detected = False
        silence_start: Optional[float] = None
        start_time = time.time()

        while (time.time() - start_time) < max_duration and not self._stop_event.is_set():
            if self._proc and self._proc.poll() is not None:
                break

            try:
                data = self._proc.stdout.read(poll_chunk)
                if not data:
                    time.sleep(0.01)
                    continue

                captured.extend(data)
                db = self.calculate_rms_db(data)

                if db > self.speech_threshold_db:
                    speech_detected = True
                    silence_start = None
                elif speech_detected:
                    if silence_start is None:
                        silence_start = time.time()
                    elif (time.time() - silence_start) >= silence_timeout:
                        # User finished speaking and paused for silence_timeout
                        break
            except Exception:
                break

        if len(captured) < self.BYTES_PER_SECOND * 0.3:  # Less than 300ms of audio
            return None

        # Convert 16-bit linear PCM bytes to float32 numpy array
        int16_data = np.frombuffer(captured, dtype=np.int16)
        waveform = int16_data.astype(np.float32) / 32768.0
        return waveform

    def stop(self) -> None:
        """Stop background streaming process."""
        self._stop_event.set()
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            finally:
                try:
                    if self._proc.stdout:
                        self._proc.stdout.close()
                    if self._proc.stderr:
                        self._proc.stderr.close()
                except Exception:
                    pass
                self._proc = None


# Global stream singleton
audio_stream = ContinuousAudioStream()
