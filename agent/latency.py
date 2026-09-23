"""End-to-end latency instrumentation and measurement for MAX."""

from __future__ import annotations
import time
from typing import Optional
from pydantic import BaseModel, Field


class LatencyReport(BaseModel):
    """End-to-end latency milestones and duration breakdown."""

    t0_wake_detected: Optional[float] = None
    t1_command_capture_start: Optional[float] = None
    t2_command_capture_end: Optional[float] = None
    t3_stt_start: Optional[float] = None
    t4_stt_end: Optional[float] = None
    t5_normalization_end: Optional[float] = None
    t6_planning_start: Optional[float] = None
    t7_planning_end: Optional[float] = None
    t8_capability_execution_start: Optional[float] = None
    t9_first_os_action_dispatched: Optional[float] = None
    t10_first_verification: Optional[float] = None
    t11_final_completion: Optional[float] = None

    @property
    def wake_detection_ms(self) -> float:
        if self.t0_wake_detected and self.t1_command_capture_start:
            return max(0.0, (self.t1_command_capture_start - self.t0_wake_detected) * 1000.0)
        return 0.0

    @property
    def command_capture_ms(self) -> float:
        if self.t1_command_capture_start and self.t2_command_capture_end:
            return max(0.0, (self.t2_command_capture_end - self.t1_command_capture_start) * 1000.0)
        return 0.0

    @property
    def stt_ms(self) -> float:
        if self.t3_stt_start and self.t4_stt_end:
            return max(0.0, (self.t4_stt_end - self.t3_stt_start) * 1000.0)
        return 0.0

    @property
    def normalization_ms(self) -> float:
        if self.t4_stt_end and self.t5_normalization_end:
            return max(0.0, (self.t5_normalization_end - self.t4_stt_end) * 1000.0)
        return 0.0

    @property
    def planning_ms(self) -> float:
        if self.t6_planning_start and self.t7_planning_end:
            return max(0.0, (self.t7_planning_end - self.t6_planning_start) * 1000.0)
        return 0.0

    @property
    def first_action_latency_ms(self) -> float:
        """Latency from speech end (T2 or T4) to first actionable OS operation (T9)."""
        ref_start = self.t2_command_capture_end or self.t4_stt_end or self.t6_planning_start
        if ref_start and self.t9_first_os_action_dispatched:
            return max(0.0, (self.t9_first_os_action_dispatched - ref_start) * 1000.0)
        return 0.0

    @property
    def verification_ms(self) -> float:
        if self.t9_first_os_action_dispatched and self.t10_first_verification:
            return max(0.0, (self.t10_first_verification - self.t9_first_os_action_dispatched) * 1000.0)
        return 0.0

    @property
    def total_task_ms(self) -> float:
        start = self.t0_wake_detected or self.t1_command_capture_start or self.t6_planning_start
        if start and self.t11_final_completion:
            return max(0.0, (self.t11_final_completion - start) * 1000.0)
        return 0.0

    def summary(self) -> dict[str, float]:
        return {
            "wake_detection_ms": round(self.wake_detection_ms, 2),
            "command_capture_ms": round(self.command_capture_ms, 2),
            "stt_ms": round(self.stt_ms, 2),
            "normalization_ms": round(self.normalization_ms, 2),
            "planning_ms": round(self.planning_ms, 2),
            "first_action_latency_ms": round(self.first_action_latency_ms, 2),
            "verification_ms": round(self.verification_ms, 2),
            "total_task_ms": round(self.total_task_ms, 2),
        }


class LatencyTracker:
    """Thread-safe context tracker for active task execution."""

    def __init__(self):
        self.current = LatencyReport()

    def reset(self) -> None:
        self.current = LatencyReport()

    def mark_wake_detected(self) -> None:
        self.current.t0_wake_detected = time.time()

    def mark_capture_start(self) -> None:
        self.current.t1_command_capture_start = time.time()

    def mark_capture_end(self) -> None:
        self.current.t2_command_capture_end = time.time()

    def mark_stt_start(self) -> None:
        self.current.t3_stt_start = time.time()

    def mark_stt_end(self) -> None:
        self.current.t4_stt_end = time.time()

    def mark_normalization_end(self) -> None:
        self.current.t5_normalization_end = time.time()

    def mark_planning_start(self) -> None:
        self.current.t6_planning_start = time.time()

    def mark_planning_end(self) -> None:
        self.current.t7_planning_end = time.time()

    def mark_execution_start(self) -> None:
        self.current.t8_capability_execution_start = time.time()

    def mark_first_action_dispatched(self) -> None:
        if self.current.t9_first_os_action_dispatched is None:
            self.current.t9_first_os_action_dispatched = time.time()

    def mark_first_verification(self) -> None:
        if self.current.t10_first_verification is None:
            self.current.t10_first_verification = time.time()

    def mark_completion(self) -> None:
        self.current.t11_final_completion = time.time()


# Global tracker
latency_tracker = LatencyTracker()
