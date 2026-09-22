"""High-resolution performance tracing and telemetry for MAX."""

import time
from typing import Optional
from pydantic import BaseModel, Field


class PerformanceTrace(BaseModel):
    """High-resolution latency breakdown using monotonic clock timestamps."""

    trace_id: str = Field(default_factory=lambda: f"tr_{int(time.time()*1000)}")
    request_text: str = ""

    # Timing metrics in milliseconds
    wake_detection_ms: float = 0.0
    wake_to_record_ms: float = 0.0
    speech_duration_ms: float = 0.0
    vad_finalization_ms: float = 0.0
    stt_duration_ms: float = 0.0
    llm_first_response_ms: float = 0.0
    tool_execution_ms: float = 0.0
    verification_ms: float = 0.0
    tts_start_ms: float = 0.0
    total_post_speech_ms: float = 0.0
    total_elapsed_ms: float = 0.0

    def compute_totals(self) -> None:
        """Compute derived latency totals from recorded metrics."""
        self.total_post_speech_ms = (
            self.vad_finalization_ms
            + self.stt_duration_ms
            + self.llm_first_response_ms
            + self.tool_execution_ms
            + self.verification_ms
        )
        if self.total_elapsed_ms <= 0.0:
            self.total_elapsed_ms = (
                self.wake_detection_ms
                + self.wake_to_record_ms
                + self.speech_duration_ms
                + self.total_post_speech_ms
            )

    def format_trace(self) -> str:
        """Format a human-readable latency breakdown table."""
        self.compute_totals()
        lines = [
            "MAX PERFORMANCE TRACE",
            f"Wake detection:          {self.wake_detection_ms:>7.1f} ms",
            f"Wake → recording:        {self.wake_to_record_ms:>7.1f} ms",
            f"Speech duration:         {self.speech_duration_ms:>7.1f} ms",
            f"VAD finalization:        {self.vad_finalization_ms:>7.1f} ms",
            f"STT:                     {self.stt_duration_ms:>7.1f} ms",
            f"LLM first response:      {self.llm_first_response_ms:>7.1f} ms",
            f"Tool execution:          {self.tool_execution_ms:>7.1f} ms",
            f"Verification:            {self.verification_ms:>7.1f} ms",
            f"TTS start:               {self.tts_start_ms:>7.1f} ms",
            f"Total post-speech:       {self.total_post_speech_ms:>7.1f} ms",
            f"Total end-to-end:        {self.total_elapsed_ms:>7.1f} ms",
        ]
        return "\n".join(lines)


class LatencyTimer:
    """Convenience context manager for measuring monotonic elapsed milliseconds."""

    def __init__(self):
        self.start_time: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed_ms = (time.perf_counter() - self.start_time) * 1000.0
        return False
