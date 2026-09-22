"""Developer and project diagnostic capability for MAX."""

from pathlib import Path
from typing import Any
from capabilities.base import Capability, Operation, ExecutionResult
from macos.shell import run_shell_command
from security.risk import RiskLevel


class DeveloperCapability(Capability):
    name = "developer"
    description = (
        "Inspect developer environments, Git repositories, active network ports/listeners, "
        "and project project definitions (Node, Python, Go, Rust, Java, Docker)."
    )

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="inspect_git_status",
                description="Inspect Git repository status, current branch, uncommitted files, and recent commit.",
                parameters={
                    "directory": {"type": "string", "description": "Repository path (defaults to current dir)"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.inspect_git_status,
            ),
            Operation(
                name="inspect_project_environment",
                description="Detect project type, package managers, and configuration files in a directory.",
                parameters={
                    "directory": {"type": "string", "description": "Project directory path"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.inspect_project_environment,
            ),
            Operation(
                name="inspect_listening_ports",
                description="Inspect which local ports are actively listening on the Mac and their owning processes.",
                parameters={
                    "port": {"type": "integer", "description": "Optional specific port number to check"},
                },
                default_risk=RiskLevel.SAFE,
                handler=self.inspect_listening_ports,
            ),
        ]

    def handle_action(self, action: str, args: dict[str, Any]) -> ExecutionResult:
        """Handle cases where the LLM sends git or dev shell commands to developer capability."""
        if action.startswith("git") or "git" in action:
            from macos.shell import run_shell_command
            cmd_str = f"{action} {' '.join(str(v) for v in args.values())}".strip()
            res = run_shell_command(cmd_str, cwd=args.get("directory", "."))
            return ExecutionResult(
                success=res.success,
                capability=self.name,
                action=action,
                data={"stdout": res.stdout, "stderr": res.stderr, "exit_code": res.exit_code},
                evidence={"stdout": res.stdout, "stderr": res.stderr},
                verification={"command_executed": True},
                error=res.stderr if not res.success else None,
            )
        raise NotImplementedError(f"Action '{action}' is not supported in '{self.name}'.")

    def inspect_git_status(self, directory: str = ".") -> ExecutionResult:
        dir_path = Path(directory).expanduser().resolve()
        res_branch = run_shell_command("git rev-parse --abbrev-ref HEAD", cwd=dir_path, timeout=3)
        if not res_branch.success:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="inspect_git_status",
                error=f"'{dir_path}' is not a Git repository or git failed: {res_branch.stderr.strip()}",
            )

        branch = res_branch.stdout.strip()
        res_status = run_shell_command("git status --short", cwd=dir_path, timeout=4)
        res_commit = run_shell_command("git log -1 --oneline", cwd=dir_path, timeout=3)

        dirty_files = [line.strip() for line in res_status.stdout.splitlines() if line.strip()]
        last_commit = res_commit.stdout.strip()

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="inspect_git_status",
            data={
                "branch": branch,
                "is_clean": len(dirty_files) == 0,
                "modified_files_count": len(dirty_files),
                "modified_files": dirty_files[:20],
                "last_commit": last_commit,
            },
            evidence={"branch": branch, "modified_count": len(dirty_files), "commit": last_commit},
            verification={"git_inspected": True},
        )

    def inspect_project_environment(self, directory: str = ".") -> ExecutionResult:
        dir_path = Path(directory).expanduser().resolve()
        indicators = {
            "node": ["package.json", "node_modules", "tsconfig.json"],
            "python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile", "poetry.lock"],
            "rust": ["Cargo.toml"],
            "go": ["go.mod"],
            "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
            "docker": ["Dockerfile", "docker-compose.yml", "compose.yaml"],
        }

        detected_types = []
        found_files = []

        for ptype, files in indicators.items():
            for f in files:
                target = dir_path / f
                if target.exists():
                    detected_types.append(ptype)
                    found_files.append(f)
                    break

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="inspect_project_environment",
            data={
                "directory": str(dir_path),
                "detected_stacks": detected_types,
                "config_files_found": found_files,
            },
            evidence={"stacks": detected_types, "files": found_files},
            verification={"directory_scanned": True},
        )

    def inspect_listening_ports(self, port: int | None = None) -> ExecutionResult:
        port_filter = f":{port}" if port else ""
        cmd = f"/usr/sbin/lsof -iTCP{port_filter} -sTCP:LISTEN -P -n"
        res = run_shell_command(cmd, timeout=5)

        lines = res.stdout.strip().splitlines()
        listeners = []
        if len(lines) > 1:
            for line in lines[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    command = parts[0]
                    pid = parts[1]
                    user = parts[2]
                    address = parts[8]
                    listeners.append({
                        "command": command,
                        "pid": pid,
                        "user": user,
                        "address": address,
                    })

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="inspect_listening_ports",
            data={"port_queried": port, "listener_count": len(listeners), "listeners": listeners},
            evidence={"count": len(listeners), "listeners": listeners[:15]},
            verification={"lsof_executed": True},
        )
