"""Background task and event-monitoring capability for MAX agent."""

from typing import Any, Optional
from capabilities.base import Capability, Operation, ExecutionResult
from security.risk import RiskLevel
from tasks.manager import TaskManager, task_manager
from tasks.models import TaskState, TaskType


class TaskCapability(Capability):
    """Capability for managing long-running background tasks, process trees, and event watchers."""

    name = "tasks"
    description = (
        "Manage asynchronous background processes, daemons, long-running test/build jobs, "
        "filesystem watchers, and service port monitoring with deterministic event notifications."
    )

    def __init__(self, manager: Optional[TaskManager] = None):
        self.manager = manager or task_manager

    def get_operations(self) -> list[Operation]:
        return [
            Operation(
                name="start_background_task",
                description="Launch a process or command in the background (dev server, build, tests, long script).",
                parameters={
                    "command": "The shell command string to execute in background",
                    "working_dir": "Optional directory path to execute within",
                    "is_daemon": "True if process runs indefinitely (e.g. server); False if it finishes on its own",
                    "max_runtime_seconds": "Optional timeout limit in seconds",
                },
                default_risk=RiskLevel.LOW,
                handler=self.start_background_task,
            ),
            Operation(
                name="list_tasks",
                description="List currently managed background tasks, processes, and watchers.",
                parameters={"status": "Optional filter: RUNNING, COMPLETED, FAILED, CANCELLED"},
                default_risk=RiskLevel.LOW,
                handler=self.list_tasks,
            ),
            Operation(
                name="get_task_status",
                description="Get detailed execution status, exit code, and PID of a managed task.",
                parameters={"task_id": "Unique task identifier (e.g. tsk_...)"},
                default_risk=RiskLevel.LOW,
                handler=self.get_task_status,
            ),
            Operation(
                name="get_task_logs",
                description="Retrieve bounded stdout/stderr log output from a background task.",
                parameters={
                    "task_id": "Unique task identifier",
                    "tail_lines": "Number of recent lines to retrieve (default: 100)",
                },
                default_risk=RiskLevel.LOW,
                handler=self.get_task_logs,
            ),
            Operation(
                name="kill_task",
                description="Terminate an active background task and its entire process tree safely.",
                parameters={"task_id": "Unique task identifier to terminate"},
                default_risk=RiskLevel.MEDIUM,
                handler=self.kill_task,
            ),
            Operation(
                name="watch_directory",
                description="Start a filesystem observer watching a directory for file creation, edits, or deletions.",
                parameters={
                    "path": "Directory path to watch",
                    "recursive": "Whether to watch subdirectories recursively (default: True)",
                },
                default_risk=RiskLevel.LOW,
                handler=self.watch_directory,
            ),
            Operation(
                name="monitor_port",
                description="Monitor a TCP port to detect when a server or service starts or stops listening.",
                parameters={
                    "port": "TCP port number to monitor (e.g. 3000, 8080)",
                    "service_name": "Optional name for the service",
                },
                default_risk=RiskLevel.LOW,
                handler=self.monitor_port,
            ),
            Operation(
                name="wait_for_task",
                description="Wait for a background task to finish without polling the LLM.",
                parameters={
                    "task_id": "Unique task identifier",
                    "timeout_seconds": "Maximum time to wait before returning current state",
                },
                default_risk=RiskLevel.LOW,
                handler=self.wait_for_task,
            ),
        ]

    def start_background_task(
        self,
        command: Optional[str] = None,
        working_dir: Optional[str] = None,
        is_daemon: bool = False,
        max_runtime_seconds: Optional[int] = None,
        **kwargs,
    ) -> ExecutionResult:
        cmd = (
            command
            or kwargs.get("cmd")
            or kwargs.get("shell_command")
            or kwargs.get("script")
            or kwargs.get("command_line")
            or kwargs.get("instruction")
            or kwargs.get("task")
            or kwargs.get("name")
        )
        if not cmd:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="start_background_task",
                error="No shell command was provided to execute in the background.",
            )

        task_type = TaskType.DAEMON if is_daemon else TaskType.COMMAND
        task = self.manager.start_task(
            command=cmd,
            working_dir=working_dir,
            task_type=task_type,
            max_runtime_seconds=max_runtime_seconds,
        )

        return ExecutionResult(
            success=task.status in (TaskState.STARTING, TaskState.RUNNING),
            capability=self.name,
            action="start_background_task",
            data={
                "task_id": task.task_id,
                "pid": task.pid,
                "pgid": task.pgid,
                "status": task.status.value,
                "command": task.command,
                "log_file": task.log_file,
            },
            evidence={
                "pid": task.pid,
                "pgid": task.pgid,
                "started_at": task.started_at,
            },
            verification={"process_spawned": task.pid is not None},
            error=task.error,
        )

    def list_tasks(self, status: Optional[str] = None, limit: int = 50, **kwargs) -> ExecutionResult:
        st_enum = None
        if status:
            try:
                st_enum = TaskState(status.upper())
            except ValueError:
                pass

        tasks = self.manager.list_tasks(status=st_enum, limit=limit)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="list_tasks",
            data={"count": len(tasks), "tasks": [t.model_dump() for t in tasks]},
            evidence={"tasks_count": len(tasks)},
            verification={"queried_database": True},
        )

    def get_task_status(self, task_id: str, **kwargs) -> ExecutionResult:
        task = self.manager.get_task(task_id)
        if not task:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="get_task_status",
                error=f"Task '{task_id}' not found.",
            )

        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_task_status",
            data=task.model_dump(),
            evidence={"status": task.status.value, "pid": task.pid, "exit_code": task.exit_code},
            verification={"exists": True},
        )

    def get_task_logs(self, task_id: str, tail_lines: int = 100, **kwargs) -> ExecutionResult:
        content, truncated = self.manager.get_logs(task_id, tail_lines=tail_lines)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="get_task_logs",
            data={"task_id": task_id, "logs": content, "truncated": truncated},
            evidence={"tail_lines": tail_lines, "truncated": truncated},
            verification={"log_read": True},
        )

    def kill_task(self, task_id: str, **kwargs) -> ExecutionResult:
        success, msg = self.manager.kill_task(task_id)
        return ExecutionResult(
            success=success,
            capability=self.name,
            action="kill_task",
            data={"task_id": task_id, "message": msg},
            evidence={"termination_message": msg},
            verification={"terminated": success},
            error=None if success else msg,
        )

    def watch_directory(self, path: str, recursive: bool = True, **kwargs) -> ExecutionResult:
        task = self.manager.watch_directory(path, recursive=recursive)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="watch_directory",
            data={
                "task_id": task.task_id,
                "watch_path": path,
                "recursive": recursive,
                "status": task.status.value,
            },
            evidence={"task_id": task.task_id},
            verification={"watcher_started": True},
        )

    def monitor_port(self, port: int, service_name: Optional[str] = None, **kwargs) -> ExecutionResult:
        task = self.manager.monitor_port(port, service_name=service_name)
        return ExecutionResult(
            success=True,
            capability=self.name,
            action="monitor_port",
            data={
                "task_id": task.task_id,
                "port": port,
                "service_name": service_name,
                "status": task.status.value,
            },
            evidence={"task_id": task.task_id},
            verification={"port_monitor_started": True},
        )

    def wait_for_task(self, task_id: str, timeout_seconds: Optional[float] = 30.0, **kwargs) -> ExecutionResult:
        task = self.manager.wait_for_task(task_id, timeout_seconds=timeout_seconds)
        if not task:
            return ExecutionResult(
                success=False,
                capability=self.name,
                action="wait_for_task",
                error=f"Task '{task_id}' not found.",
            )

        return ExecutionResult(
            success=task.is_terminal,
            capability=self.name,
            action="wait_for_task",
            data=task.model_dump(),
            evidence={"status": task.status.value, "exit_code": task.exit_code},
            verification={"terminal_state_reached": task.is_terminal},
        )
