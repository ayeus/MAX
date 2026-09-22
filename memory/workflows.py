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
    results: list[ExecutionResult] = Field(default_factory=list)


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
            with conn:
                conn.execute(
                    """
                    INSERT INTO workflows (name, description, steps_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        description = excluded.description,
                        steps_json = excluded.steps_json
                    """,
                    (name_clean, description, steps_json),
                )

            # 2. Write JSON file to ~/.max/workflows/<name>.json
            json_path = self.workflows_dir / f"{name_clean}.json"
            json_path.write_text(wf.model_dump_json(indent=2), encoding="utf-8")
            return True
        except Exception:
            return False

    def get_workflow(self, name: str) -> Workflow | None:
        """Get workflow from SQLite or JSON file."""
        name_clean = name.strip().lower().replace(" ", "_")
        conn = get_db_connection()
        cur = conn.execute("SELECT * FROM workflows WHERE name = ?", (name_clean,))
        row = cur.fetchone()
        if row:
            steps_data = json.loads(row["steps_json"])
            steps = [WorkflowStep(**s) for s in steps_data]
            return Workflow(
                name=row["name"],
                description=row["description"] or "",
                steps=steps,
                created_at=str(row["created_at"]),
            )

        # Fallback to JSON file if present
        json_path = self.workflows_dir / f"{name_clean}.json"
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                return Workflow(**data)
            except Exception:
                pass
        return None

    def list_workflows(self) -> list[dict[str, Any]]:
        """List all available workflows."""
        conn = get_db_connection()
        cur = conn.execute("SELECT name, description, created_at FROM workflows ORDER BY created_at DESC")
        return [
            {"name": r["name"], "description": r["description"], "created_at": str(r["created_at"])}
            for r in cur.fetchall()
        ]

    def execute_workflow(self, name: str) -> WorkflowExecutionReport:
        """Replay all steps of a saved workflow in sequence."""
        from capabilities import initialize_default_capabilities
        initialize_default_capabilities()

        wf = self.get_workflow(name)
        if not wf:
            return WorkflowExecutionReport(workflow_name=name, success=False)

        results = []
        overall_success = True

        for step in wf.steps:
            res = registry.execute(
                capability_name=step.capability,
                action=step.action,
                args=step.args,
            )
            results.append(res)
            if not res.success:
                overall_success = False

        return WorkflowExecutionReport(
            workflow_name=name,
            success=overall_success,
            results=results,
        )


workflow_manager = WorkflowManager()
