"""Outcome-to-plan translation using LLM for MAX."""

import json
import re
from typing import Any
from pydantic import BaseModel, Field
from llm.model_manager import model_manager
from llm.prompts import SYSTEM_PROMPT, build_planning_prompt
from capabilities.registry import registry
from .context import AgentContext


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
        """Call LLM to formulate an execution plan to accomplish the user's requested outcome."""
        schemas = registry.get_all_schemas()
        prompt = build_planning_prompt(
            user_request=user_request,
            environment_context=context.to_prompt_dict(),
            capabilities_schema=schemas,
            recent_history=context.recent_history,
        )

        response = self.provider.generate(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            json_format=True,
            temperature=0.1,
        )

        cleaned = clean_json_response(response.content)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                thought = "Executing plan to achieve outcome"
                raw_steps = parsed
            elif isinstance(parsed, dict):
                thought = parsed.get("thought", "Executing plan to achieve outcome")
                raw_steps = parsed.get("plan", [])
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
                    steps.append(PlanStep(
                        step_number=s.get("step_number", i),
                        capability=str(s.get("capability", "terminal")).lower(),
                        action=str(s.get("action", "execute_command")),
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

            if not steps:
                req_lower = user_request.lower()
                if "window" in req_lower:
                    steps.append(PlanStep(
                        step_number=1,
                        capability="accessibility",
                        action="get_active_window_info",
                        args={},
                        verification_criteria="Active window details",
                    ))
                else:
                    steps.append(PlanStep(
                        step_number=1,
                        capability="terminal",
                        action="execute_command",
                        args={"command": f"echo '{user_request}'"},
                        verification_criteria="None",
                    ))

            return Plan(thought=thought, plan=steps)
        except Exception as e:
            # Fallback if model output is not valid JSON
            return Plan(
                thought=f"Direct interpretation of task: '{user_request}'",
                plan=[
                    PlanStep(
                        step_number=1,
                        capability="terminal",
                        action="execute_command",
                        args={"command": f"echo 'Could not formulate plan: {e}'"},
                        verification_criteria="None",
                        is_optional=False,
                    )
                ],
            )
