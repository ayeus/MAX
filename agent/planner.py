"""Outcome-to-plan translation using LLM for MAX with hard capability gating."""

from __future__ import annotations
import json
import logging
import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
from llm.model_manager import model_manager
from llm.prompts import SYSTEM_PROMPT, build_planning_prompt
from capabilities.registry import registry
from .context import AgentContext
from .intent import intent_resolver
from voice.normalization import normalizer

logger = logging.getLogger(__name__)


class PlannerStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"


class PlanStep(BaseModel):
    step_number: int
    capability: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    verification_criteria: str = ""
    is_optional: bool = False


class Plan(BaseModel):
    thought: str
    plan: list[PlanStep] = Field(default_factory=list)
    status: PlannerStatus = PlannerStatus.VALID
    rejection_reason: Optional[str] = None
    unsupported_operations: list[str] = Field(default_factory=list)


def clean_json_response(raw_text: str) -> str:
    """Extract raw JSON from model output, stripping markdown code fences if present."""
    text = raw_text.strip()
    # Strip ```json ... ```
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
    return text


class Planner:
    """Decomposes natural language requests into structured capability steps."""

    def __init__(self, provider=None):
        self._provider = provider

    @property
    def provider(self):
        return self._provider or model_manager.provider

    def create_plan(self, user_request: str, context: AgentContext) -> Plan:
        """Call LLM or fast-path resolver to formulate an execution plan to accomplish the outcome."""
        # 1. Ambiguity Gate: If target or intent is unclear, ask for clarification immediately
        interp = normalizer.normalize(user_request)
        if interp.is_ambiguous and interp.clarification_prompt:
            return Plan(
                thought=interp.clarification_prompt,
                plan=[],
                status=PlannerStatus.AMBIGUOUS,
                rejection_reason=interp.ambiguity_reason or "Ambiguous user request",
            )

        # 1b. Hard Capability Gate for known unsupported hardware/OS settings
        unsupported_hardware = [
            (re.compile(r"\b(?:refresh\s+rate|hz)\b", re.IGNORECASE), "refresh rate"),
            (re.compile(r"\b(?:overclock|clock\s+speed)\b", re.IGNORECASE), "CPU/GPU overclocking"),
            (re.compile(r"\bfan\s+speed\b", re.IGNORECASE), "fan speed"),
            (re.compile(r"\bbluetooth\b", re.IGNORECASE), "bluetooth"),
            (re.compile(r"\bnight\s+shift\b", re.IGNORECASE), "Night Shift"),
            (re.compile(r"\btrue\s+tone\b", re.IGNORECASE), "True Tone"),
        ]
        for pat, feat in unsupported_hardware:
            if pat.search(user_request):
                return Plan(
                    thought=f"I can't change the {feat} yet because I don't have a supported capability for that.",
                    plan=[],
                    status=PlannerStatus.UNSUPPORTED,
                    rejection_reason=f"Unsupported hardware/system feature: {feat}",
                    unsupported_operations=[feat],
                )

        # 2. Deterministic Fast-Path: Resolve high-confidence common intents directly
        fast_plan = intent_resolver.resolve(user_request)
        if fast_plan and fast_plan.plan:
            # Verify that all steps in fast_plan are genuinely registered
            if all(registry.is_operation_supported(s.capability, s.action) for s in fast_plan.plan):
                logger.debug(f"Resolved '{user_request}' via deterministic fast-path: {fast_plan.thought}")
                fast_plan.status = PlannerStatus.VALID
                return fast_plan

        # 3. LLM Reasoning Planning
        if not self._provider:
            from llm.model_manager import ModelCapability
            model_manager.verify_and_resolve_model(ModelCapability.REASONING)

        schemas = registry.get_all_schemas()
        prompt = build_planning_prompt(
            user_request=user_request,
            environment_context=context.to_prompt_dict(),
            capabilities_schema=schemas,
            recent_history=context.recent_history,
        )

        try:
            response = self.provider.generate(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                json_format=True,
                temperature=0.1,
            )
            cleaned = clean_json_response(response.content)
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                thought = "Executing plan to achieve outcome"
                raw_steps = parsed
            elif isinstance(parsed, dict):
                thought = parsed.get("thought", "Executing plan to achieve outcome")
                raw_steps = parsed.get("plan", [])
                while isinstance(raw_steps, dict) and "plan" in raw_steps:
                    raw_steps = raw_steps["plan"]
                if isinstance(raw_steps, dict):
                    raw_steps = [raw_steps]
                elif not isinstance(raw_steps, list):
                    raw_steps = []
            else:
                thought = str(parsed)
                raw_steps = []

            steps = []
            for i, s in enumerate(raw_steps, 1):
                if isinstance(s, dict):
                    while "plan" in s and isinstance(s["plan"], dict):
                        s = s["plan"]
                    cap = str(s.get("capability", "terminal")).lower()
                    act = str(s.get("action", "execute_command"))
                    steps.append(PlanStep(
                        step_number=s.get("step_number", i),
                        capability=cap,
                        action=act,
                        args=s.get("args", {}) if isinstance(s.get("args"), dict) else {},
                        verification_criteria=str(s.get("verification_criteria", "")),
                        is_optional=bool(s.get("is_optional", False)),
                    ))
                elif isinstance(s, str):
                    steps.append(PlanStep(
                        step_number=i,
                        capability="terminal",
                        action="execute_command",
                        args={"command": s},
                        verification_criteria="None",
                        is_optional=False,
                    ))

            # ATOMIC CAPABILITY GATING & PLAN VALIDATION
            # If ANY mandatory step requires an unsupported operation, the ENTIRE plan is rejected.
            unregistered_mandatory = []
            for s in steps:
                if not s.is_optional and not registry.is_operation_supported(s.capability, s.action):
                    unregistered_mandatory.append(f"{s.capability}.{s.action}")

            if unregistered_mandatory:
                return Plan(
                    thought=f"I cannot perform this request because the required operation(s) {unregistered_mandatory} are not supported.",
                    plan=[],
                    status=PlannerStatus.UNSUPPORTED,
                    rejection_reason=f"Required operation(s) {unregistered_mandatory} are not supported by the capability registry.",
                    unsupported_operations=unregistered_mandatory,
                )

            # Filter out blank terminal commands or unsupported OPTIONAL steps
            valid_steps = []
            for s in steps:
                if s.capability == "terminal" and s.action == "execute_command" and not s.args.get("command", "").strip():
                    continue
                if s.is_optional and not registry.is_operation_supported(s.capability, s.action):
                    logger.warning(f"Omitting unsupported optional step: {s.capability}.{s.action}")
                    continue
                valid_steps.append(s)

            if not valid_steps:
                req_lower = user_request.lower()
                # If this is a continuation prompt and no further steps are needed, return empty plan
                if "formulate the next" in req_lower or "steps already completed" in req_lower:
                    return Plan(thought=thought or "All necessary steps completed.", plan=[], status=PlannerStatus.VALID)

                return Plan(
                    thought=thought or f"Unable to formulate executable plan for '{user_request}'",
                    plan=[],
                    status=PlannerStatus.INVALID,
                    rejection_reason="No executable steps generated.",
                )

            return Plan(thought=thought, plan=valid_steps, status=PlannerStatus.VALID)
        except Exception as e:
            # Explicit failure representation, never run a no-op command to mask planning failure
            return Plan(
                thought=f"Planning failure for '{user_request}': {e}",
                plan=[],
                status=PlannerStatus.INVALID,
                rejection_reason=f"Planning exception: {e}",
            )

