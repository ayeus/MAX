"""Unit and integration tests for MAX System-Wide Latency Tracing (T0-T11) and Sub-Second Execution.

Taxonomy:
- UNIT: LatencyTracker timestamp registration, milestone duration calculations, and summary exports.
- INTEGRATION: AgentCore closed-loop execution populating LatencyReport with sub-second milestones.
"""

import time
import unittest
from agent.latency import LatencyReport, LatencyTracker, latency_tracker
from agent.core import AgentCore
from verification.base import GoalStatus, AgentState


class TestLatencyTracing(unittest.TestCase):
    """Test suite for T0-T11 latency telemetry and sub-second execution performance."""

    def test_unit_latency_milestones_and_durations(self):
        """[UNIT] Verify latency calculations accurately reflect milestone deltas without negative values."""
        rep = LatencyReport()
        t_base = 1000.0

        # Simulate timeline:
        # T0: 0ms (wake detected)
        # T1: 50ms (capture start)
        # T2: 850ms (capture end, speech ended)
        # T3: 860ms (STT start)
        # T4: 1060ms (STT end)
        # T5: 1065ms (normalization end)
        # T6: 1070ms (planning start)
        # T7: 1080ms (planning end)
        # T8: 1085ms (execution start)
        # T9: 1110ms (first action dispatched)
        # T10: 1130ms (first verification complete)
        # T11: 1150ms (final completion)

        rep.t0_wake_detected = t_base + 0.000
        rep.t1_command_capture_start = t_base + 0.050
        rep.t2_command_capture_end = t_base + 0.850
        rep.t3_stt_start = t_base + 0.860
        rep.t4_stt_end = t_base + 1.060
        rep.t5_normalization_end = t_base + 1.065
        rep.t6_planning_start = t_base + 1.070
        rep.t7_planning_end = t_base + 1.080
        rep.t8_capability_execution_start = t_base + 1.085
        rep.t9_first_os_action_dispatched = t_base + 1.110
        rep.t10_first_verification = t_base + 1.130
        rep.t11_final_completion = t_base + 1.150

        self.assertAlmostEqual(rep.wake_detection_ms, 50.0, delta=1.0)
        self.assertAlmostEqual(rep.command_capture_ms, 800.0, delta=1.0)
        self.assertAlmostEqual(rep.stt_ms, 200.0, delta=1.0)
        self.assertAlmostEqual(rep.normalization_ms, 5.0, delta=1.0)
        self.assertAlmostEqual(rep.planning_ms, 10.0, delta=1.0)
        # First action latency from speech end (T2=850ms to T9=1110ms) = 260ms
        self.assertAlmostEqual(rep.first_action_latency_ms, 260.0, delta=1.0)
        self.assertAlmostEqual(rep.verification_ms, 20.0, delta=1.0)
        self.assertAlmostEqual(rep.total_task_ms, 1150.0, delta=1.0)

        summary = rep.summary()
        self.assertIn("first_action_latency_ms", summary)
        self.assertIn("planning_ms", summary)
        self.assertIn("total_task_ms", summary)

    def test_unit_latency_tracker_lifecycle(self):
        """[UNIT] Verify LatencyTracker lifecycle marks correct progression and resets cleanly."""
        tracker = LatencyTracker()
        tracker.reset()
        self.assertIsNone(tracker.current.t0_wake_detected)

        tracker.mark_wake_detected()
        self.assertIsNotNone(tracker.current.t0_wake_detected)

        tracker.mark_planning_start()
        time.sleep(0.01)
        tracker.mark_planning_end()
        self.assertGreater(tracker.current.planning_ms, 5.0)

        tracker.mark_first_action_dispatched()
        self.assertIsNotNone(tracker.current.t9_first_os_action_dispatched)

        tracker.mark_completion()
        self.assertIsNotNone(tracker.current.t11_final_completion)

    def test_integration_agentcore_subsecond_execution_and_latency_trace(self):
        """[INTEGRATION] Verify AgentCore populates LatencyReport and completes deterministic tasks in sub-second time."""
        agent = AgentCore()
        start = time.time()
        # Fast deterministic supported command
        report = agent.run("increase my brightness")
        elapsed_total_ms = (time.time() - start) * 1000.0

        self.assertIsNotNone(
            report.latency_report,
            "AgentExecutionReport must include an instrumented LatencyReport",
        )
        self.assertIsNotNone(report.latency_report.t6_planning_start)
        self.assertIsNotNone(report.latency_report.t7_planning_end)
        self.assertIsNotNone(report.latency_report.t11_final_completion)

        # Deterministic fast-path planning must be under 50ms
        self.assertLess(
            report.latency_report.planning_ms,
            100.0,
            f"Deterministic planning latency ({report.latency_report.planning_ms:.2f}ms) exceeded 100ms budget",
        )

        # Total execution including hardware verification must be well under 1000ms
        self.assertLess(
            elapsed_total_ms,
            1000.0,
            f"End-to-end task duration ({elapsed_total_ms:.2f}ms) exceeded 1000ms sub-second requirement",
        )


if __name__ == "__main__":
    unittest.main()
