"""General terminal capability for MAX.

Allows MAX to execute arbitrary legitimate shell commands, inspect outputs,
and verify state changes on macOS.
"""

from typing import Any
from capabilities.base import Capability, Operation, ExecutionResult
from macos.shell import run_shell_command
from security.risk import RiskLevel, assess_command_risk
from security.policy import SecurityPolicy, PolicyViolation
from security.confirmation import request_user_confirmation
from security.audit import audit_log
from app.config import settings
import shutil


class TerminalCapability(Capability):
    name = "terminal"
    description = (
        "Execute general shell commands, CLI utilities, build tools, package managers, "
        "and diagnosis scripts on macOS."
    )

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="execute_command",
                description="Execute an arbitrary shell command on macOS via zsh, capturing stdout, stderr, and exit code.",
                parameters={
                    "command": {"type": "string", "description": "The exact shell command to execute"},
                    "cwd": {"type": "string", "description": "Optional working directory path (defaults to current dir)"},
                    "timeout": {"type": "integer", "description": "Optional timeout in seconds"},
                },
                default_risk=RiskLevel.LOW,
                handler=self.execute_command,
            ),
            Operation(
                name="check_tool_installed",
                description="Verify if a CLI binary/tool exists in the system PATH.",
                parameters={
                    "tool_name": {"type": "string", "description": "Binary name to look for (e.g. 'docker', 'git', 'node')"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.check_tool_installed,
            ),
        ]

    def handle_action(self, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Handle cases where the planner LLM uses the command name directly as the action."""
        cmd = args.get("command") or args.get("cmd") or args.get("args")
        if cmd:
            full_cmd = f"{action} {cmd}".strip()
        elif args:
            # Join argument values if provided
            joined_args = " ".join(str(v) for v in args.values())
            full_cmd = f"{action} {joined_args}".strip()
        else:
            full_cmd = action.strip()

        cwd = args.get("cwd")
        timeout = args.get("timeout")
        return self.execute_command(command=full_cmd, cwd=cwd, timeout=timeout)

    def execute_command(
        self,
        command: str = "",
        cwd: str | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Execute a shell command with security policy enforcement and evidence capture."""
        cmd_str = (command or "").strip()
        if not cmd_str:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="execute_command",
                error="No shell command was provided to execute.",
            )

        audit_log.log_event(
            event_type="tool_requested",
            tool=self.name,
            action="execute_command",
            details={"command": cmd_str, "cwd": cwd},
        )

        # 1. Risk Assessment & Policy Check
        try:
            risk_assessment = self.policy.evaluate_command(cmd_str)
        except PolicyViolation as pv:
            audit_log.log_event(
                event_type="tool_failed",
                tool=self.name,
                action="execute_command",
                risk_level=RiskLevel.BLOCKED.value,
                details={"reason": str(pv)},
                success=False,
            )
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="execute_command",
                error=str(pv),
                data={"command": cmd_str},
            )

        # 2. Confirmation Check for High Risk Actions
        if risk_assessment.requires_confirmation and settings.require_confirmation_for_high_risk:
            audit_log.log_event(
                event_type="confirmation_requested",
                tool=self.name,
                action="execute_command",
                risk_level=risk_assessment.level.value,
                details={"reason": risk_assessment.reason},
            )
            confirmed = request_user_confirmation(
                action_description=f"MAX requested to execute command: `{cmd_str}`\nReason for warning: {risk_assessment.reason}",
                targets=risk_assessment.affected_targets,
            )
            audit_log.log_event(
                event_type="confirmation_received",
                tool=self.name,
                action="execute_command",
                details={"confirmed": confirmed},
            )
            if not confirmed:
                return ExecutionResult(
                    success=False,
                    capability=self.name,
                    action="execute_command",
                    error="Operation cancelled by user.",
                    data={"command": cmd_str, "status": "user_rejected"},
                )

        # 3. Execution
        audit_log.log_event(
            event_type="tool_started",
            tool=self.name,
            action="execute_command",
            risk_level=risk_assessment.level.value,
        )

        res = run_shell_command(
            command=cmd_str,
            cwd=cwd,
            timeout=timeout,
        )

        # 4. Result and Evidence Packaging
        audit_log.log_event(
            event_type="tool_completed" if res.success else "tool_failed",
            tool=self.name,
            action="execute_command",
            details={
                "exit_code": res.exit_code,
                "stdout_len": len(res.stdout),
                "stderr_len": len(res.stderr),
                "duration_ms": res.duration_ms,
            },
            success=res.success,
        )

        return ExecutionResult(
            success=res.success,
            capability=self.name,
            action="execute_command",
            data={
                "command": cmd_str,
                "exit_code": res.exit_code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "timed_out": res.timed_out,
            },
            evidence={
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.exit_code,
            },
            verification={
                "command_executed": True,
                "zero_exit_code": res.exit_code == 0,
            },
            duration_ms=res.duration_ms,
            error=res.stderr if not res.success else None,
        )

    def check_tool_installed(self, tool_name: str) -> ExecutionResult:
        """Check if binary is installed on PATH."""
        path = shutil.which(tool_name.strip())
        is_installed = path is not None
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="check_tool_installed",
            data={
                "tool": tool_name,
                "installed": is_installed,
                "path": path,
            },
            evidence={
                "installed": is_installed,
                "path": path,
            },
            verification={"queried_path": True},
        )
