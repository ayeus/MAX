"""Telemetry and performance instrumentation for MAX."""

from .tracing import PerformanceTrace, LatencyTimer

__all__ = ["PerformanceTrace", "LatencyTimer"]
