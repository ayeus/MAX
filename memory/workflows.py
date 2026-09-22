"""Reusable workflow procedures management for MAX."""

from pathlib import Path
from pydantic import BaseModel, Field
import json
from datetime import datetime, timezone
from typing import Any
from .database import get_db_connection
from app.config import settings
from capabilities.registry import registry
from capabilities.base import ExecutionResult


class WorkflowStep(BaseModel):
    step_number: int
    capability: str
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    verification_criteria: str = ""


class Workflow(BaseModel):
    name: str
    description: str
    steps: list[WorkflowStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorkflowExecutionReport(BaseModel):
    workflow_name: str
    success: bool
    status: Any = "UNKNOWN"
    explanation: str = ""
    results: list[ExecutionResult] = Field(default_factory=list)
    verifications: list[Any] = Field(default_factory=list)


class WorkflowManager:
    """Manages persistent and user-editable workflow definitions."""

    def __init__(self, workflows_dir: Path = settings.workflows_dir):
        self.workflows_dir = workflows_dir
        self.workflows_dir.mkdir(parents=True, exist_ok=True)

    def save_workflow(self, name: str, description: str, steps: list[dict[str, Any]]) -> bool:
        """Save a workflow definition to SQLite and export as human-readable JSON."""
        name_clean = name.strip().lower().replace(" ", "_")
        steps_models = [
            WorkflowStep(
                step_number=s.get("step_number", i),
                capability=s.get("capability", "terminal"),
                action=s.get("action", "execute_command"),
                args=s.get("args", {}),
                verification_criteria=s.get("verification_criteria", ""),
            )
            for i, s in enumerate(steps, 1)
        ]

        wf = Workflow(name=name_clean, description=description, steps=steps_models)
        steps_json = json.dumps([s.model_dump() for s in steps_models], indent=2)

        # 1. Save to SQLite
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO workflows (name, description, steps_json)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    steps_json = excluded.steps_json
                """,
                (wf.name, wf.description, steps_json),
            )
            conn.commit()
        finally:
            conn.close()

        # 2. Export to JSON file in ~/.max/workflows/
        file_path = self.workflows_dir / f"{wf.name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(wf.model_dump_json(indent=2))

        return True

    def get_workflow(self, name: str) -> Workflow | None:
        """Retrieve workflow by name from SQLite."""
        name_clean = name.strip().lower().replace(" ", "_")
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT name, description, steps_json, created_at FROM workflows WHERE name = ?",
                (name_clean,),
            ).fetchone()
            if not row:
                return None

            steps_data = json.loads(row["steps_json"])
            steps = [WorkflowStep(**s) for s in steps_data]
            return Workflow(
                name=row["name"],
                description=row["description"],
                steps=steps,
                created_at=str(row["created_at"]),
            )
        finally:
            conn.close()

    def list_workflows(self) -> list[dict[str, str]]:
        """List all saved workflows."""
        conn = get_db_connection()
        try:
            cur = conn.execute("SELECT name, description, created_at FROM workflows ORDER BY created_at DESC")
            return [
                {"name": r["name"], "description": r["description"], "created_at": str(r["created_at"])}
                for r in cur.fetchall()
            ]
        finally:
            conn.close()

    def execute_workflow(self, name: str) -> WorkflowExecutionReport:
        """Replay all steps of a saved workflow in sequence with closed-loop goal verification."""
        from capabilities import initialize_default_capabilities
        from agent.observer import observer
        from agent.planner import PlanStep
        from agent.core import StepExecutionRecord
        from verification import GoalStatus, goal_evaluator

        initialize_default_capabilities()

        wf = self.get_workflow(name)
        if not wf:
            return WorkflowExecutionReport(
                workflow_name=name,
                success=False,
                status=GoalStatus.UNKNOWN,
                explanation=f"Workflow '{name}' not found.",
            )

        results = []
        verifications = []
        executed_records: list[StepExecutionRecord] = []
        plan_steps = [
            PlanStep(
                step_number=s.step_number,
                capability=s.capability,
                action=s.action,
                args=s.args,
                verification_criteria=s.verification_criteria,
                is_optional=False,
            )
            for s in wf.steps
        ]

        remaining_queue = list(plan_steps)
        obs = observer.observe(fast=True)

        for step in plan_steps:
            remaining_queue.pop(0)
            res = registry.execute(
                capability_name=step.capability,
                action=step.action,
                args=step.args,
            )
            results.append(res)
            obs = observer.observe(fast=True)
            verif = goal_evaluator.evaluate_step(step, res, obs)
            verifications.append(verif)

            record = StepExecutionRecord(
                step=step,
                result=res,
                observation_after={
                    "active_application": obs.active_application,
                    "current_directory": obs.current_directory,
                },
                verification=verif,
            )
            executed_records.append(record)

            # If step verification is not satisfied, stop executing remainder
            if verif.status != GoalStatus.SATISFIED:
                break

        goal_eval = goal_evaluator.evaluate_goal(
            user_request=wf.description or wf.name,
            steps_executed=executed_records,
            remaining_steps=remaining_queue,
            last_observation=obs,
        )

        is_satisfied = (goal_eval.status == GoalStatus.SATISFIED)

        return WorkflowExecutionReport(
            workflow_name=name,
            success=is_satisfied,
            status=goal_eval.status,
            explanation=goal_eval.explanation,
            results=results,
            verifications=verifications,
        )


workflow_manager = WorkflowManager()
