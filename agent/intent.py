"""Deterministic intent resolver for high-confidence computer-use operations.

Bypasses general-purpose LLM latency for simple, high-confidence commands
while strictly producing standard PlanSteps that execute real registered capabilities
and undergo full independent observation and state-delta verification.
"""

from __future__ import annotations
import logging
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from agent.planner import Plan, PlanStep
from voice.normalization import normalizer, SpeechInterpretation
from capabilities.registry import registry

logger = logging.getLogger(__name__)


class IntentResolver:
    """Resolves normalized user utterances into executable single-step Plans when confidence is high."""

    def resolve(self, user_request: str) -> Optional[Plan]:
        """Attempt to resolve request to a deterministic Plan using reusable linguistic normalization."""
        from agent.planner import Plan, PlanStep

        interp = normalizer.normalize(user_request)


        # Ambiguous commands must not be resolved deterministically to a wrong guess
        if interp.is_ambiguous:
            return None

        intent = interp.intent
        if not intent:
            return None

        # 1. Brightness adjustments
        if intent == "increase_brightness":
            if registry.is_operation_supported("macos", "increase_brightness"):
                delta = interp.parameters.get("delta", 0.1)
                return Plan(
                    thought=f"Increasing display brightness by {delta} via native macOS DisplayServices.",
                    plan=[
                        PlanStep(
                            step_number=1,
                            capability="macos",
                            action="increase_brightness",
                            args={"delta": delta},
                            verification_criteria="Display brightness increased in OS state",
                            is_optional=False,
                        )
                    ],
                )

        elif intent == "decrease_brightness":
            if registry.is_operation_supported("macos", "decrease_brightness"):
                delta = interp.parameters.get("delta", 0.1)
                return Plan(
                    thought=f"Decreasing display brightness by {delta} via native macOS DisplayServices.",
                    plan=[
                        PlanStep(
                            step_number=1,
                            capability="macos",
                            action="decrease_brightness",
                            args={"delta": delta},
                            verification_criteria="Display brightness decreased in OS state",
                            is_optional=False,
                        )
                    ],
                )

        # 2. Application Launching (high-confidence single app target)
        elif intent == "launch_application" and interp.target:
            app_name = interp.target
            if registry.is_operation_supported("applications", "launch_application"):
                return Plan(
                    thought=f"Launching application '{app_name}'.",
                    plan=[
                        PlanStep(
                            step_number=1,
                            capability="applications",
                            action="launch_application",
                            args={"application_name": app_name},
                            verification_criteria=f"Application '{app_name}' verified running in OS process list",
                            is_optional=False,
                        )
                    ],
                )

        # 3. Application Quitting (high-confidence single app target)
        elif intent == "quit_application" and interp.target:
            app_name = interp.target
            if registry.is_operation_supported("applications", "quit_application"):
                return Plan(
                    thought=f"Quitting application '{app_name}'.",
                    plan=[
                        PlanStep(
                            step_number=1,
                            capability="applications",
                            action="quit_application",
                            args={"application_name": app_name},
                            verification_criteria=f"Application '{app_name}' process terminated",
                            is_optional=False,
                        )
                    ],
                )

        # 4. Close Active Window (standard Cmd+W shortcut)
        elif intent == "close_window":
            if registry.is_operation_supported("accessibility", "send_key_chord"):
                return Plan(
                    thought="Closing active frontmost window via Command+W.",
                    plan=[
                        PlanStep(
                            step_number=1,
                            capability="accessibility",
                            action="send_key_chord",
                            args={"key": "w", "modifiers": "command"},
                            verification_criteria="Active window closed",
                            is_optional=False,
                        )
                    ],
                )

        return None


intent_resolver = IntentResolver()
