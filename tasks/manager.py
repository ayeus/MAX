"""Unified Task Manager coordinating background processes, watchers, persistence, and event notifications in MAX."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
from typing import Optional
from event_engine.bus import EventBus, global_event_bus
from event_engine.events import EventType, TaskCompletedEvent, TaskFailedEvent, TaskCancelledEvent
from tasks.models import ManagedTask, TaskState, TaskType
from tasks.persistence import (
    init_tasks_schema,
    save_task,
    get_task as db_get_task,
    list_tasks as db_list_tasks,
    reconcile_orphan_tasks,
)
from tasks.supervisor import ProcessSupervisor
from tasks.watchers import DirectoryWatcher, PortWatcher

logger = logging.getLogger(__name__)


class TaskManager:
    """Central manager for MAX long-running tasks, daemons, watchers, and event subscriptions."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or global_event_bus
        self.supervisor = ProcessSupervisor(self.event_bus)
        self._watchers: dict[str, DirectoryWatcher] = {}
        self._port_monitors: dict[str, PortWatcher] = {}
        self._lock = threading.RLock()

        # Initialize schema and reconcile startup orphans
        init_tasks_schema()
        self.reconcile_orphans()

    def reconcile_orphans(self) -> list[ManagedTask]:
        """Reconcile persisted tasks with actual OS processes on startup."""
        reconciled = reconcile_orphan_tasks()
        if reconciled:
            logger.info(f"Reconciled {len(reconciled)} orphaned background tasks from previous sessions.")
        return reconciled

    def start_task(
        self,
        command: str,
        working_dir: Optional[str] = None,
        task_type: TaskType = TaskType.COMMAND,
        max_runtime_seconds: Optional[int] = None,
        original_request: Optional[str] = None,
    ) -> ManagedTask:
        """Launch and register a supervised background task."""
        return self.supervisor.launch_task(
            command=command,
            working_dir=working_dir,
            task_type=task_type,
            max_runtime_seconds=max_runtime_seconds,
            original_request=original_request,
        )

    def watch_directory(
        self,
        path: str,
        recursive: bool = True,
        original_request: Optional[str] = None,
    ) -> ManagedTask:
        """Create a managed filesystem watcher task."""
        abs_path = str(Path(path).resolve())
        task = ManagedTask(
            command=f"watch {abs_path} (recursive={recursive})",
            task_type=TaskType.FS_WATCHER,
            status=TaskState.RUNNING,
            working_dir=abs_path,
            started_at=datetime.now(timezone.utc).isoformat(),
            original_request=original_request,
            metadata={"watch_path": abs_path, "recursive": recursive},
        )
        save_task(task)

        watcher = DirectoryWatcher(
            watch_path=abs_path,
            recursive=recursive,
            event_bus=self.event_bus,
            task_id=task.task_id,
        )
        watcher.start()

        with self._lock:
            self._watchers[task.task_id] = watcher

        return task

    def monitor_port(
        self,
        port: int,
        host: str = "127.0.0.1",
        service_name: Optional[str] = None,
        original_request: Optional[str] = None,
    ) -> ManagedTask:
        """Create a managed service / TCP port monitor task."""
        svc = service_name or f"Port-{port}"
        task = ManagedTask(
            command=f"monitor port {host}:{port} ({svc})",
            task_type=TaskType.PORT_MONITOR,
            status=TaskState.RUNNING,
            started_at=datetime.now(timezone.utc).isoformat(),
            original_request=original_request,
            metadata={"port": port, "host": host, "service_name": svc},
        )
        save_task(task)

        pw = PortWatcher(
            port=port,
            host=host,
            service_name=svc,
            event_bus=self.event_bus,
            task_id=task.task_id,
        )
        pw.start()

        with self._lock:
            self._port_monitors[task.task_id] = pw

        return task

    def get_task(self, task_id: str) -> Optional[ManagedTask]:
        """Retrieve task by unique identifier."""
        return db_get_task(task_id)

    def list_tasks(self, status: Optional[TaskState] = None, limit: int = 50) -> list[ManagedTask]:
        """List managed tasks from database."""
        return db_list_tasks(status=status, limit=limit)

    def kill_task(self, task_id: str, reason: str = "User requested cancellation") -> tuple[bool, str]:
        """Terminate an active task (process, watcher, or monitor)."""
        task = self.get_task(task_id)
        if not task:
            return False, f"Task '{task_id}' not found."

        # 1. Check if it is a directory watcher
        with self._lock:
            if task_id in self._watchers:
                w = self._watchers.pop(task_id)
                w.stop()
                task.status = TaskState.CANCELLED
                task.finished_at = datetime.now(timezone.utc).isoformat()
                task.error = reason
                save_task(task)
                return True, f"Filesystem watcher task '{task_id}' stopped."

            # 2. Check if it is a port monitor
            if task_id in self._port_monitors:
                pm = self._port_monitors.pop(task_id)
                pm.stop()
                task.status = TaskState.CANCELLED
                task.finished_at = datetime.now(timezone.utc).isoformat()
                task.error = reason
                save_task(task)
                return True, f"Port monitor task '{task_id}' stopped."

        # 3. Supervised subprocess
        return self.supervisor.terminate_task(task_id, reason=reason)

    def get_logs(self, task_id: str, tail_lines: int = 100) -> tuple[str, bool]:
        """Retrieve bounded logs for a task."""
        return self.supervisor.get_logs(task_id, tail_lines=tail_lines)

    def wait_for_task(self, task_id: str, timeout_seconds: Optional[float] = None) -> Optional[ManagedTask]:
        """Wait deterministically for a task to reach terminal state without polling the LLM."""
        task = self.get_task(task_id)
        if not task or task.is_terminal:
            return task

        # Listen for task completion/failure/cancellation on event bus
        ev = self.event_bus.wait_for(
            event_type="*",
            filter_fn=lambda e: (
                e.task_id == task_id and
                e.event_type in (
                    EventType.TASK_COMPLETED,
                    EventType.TASK_FAILED,
                    EventType.TASK_CANCELLED,
                    EventType.TASK_TIMED_OUT,
                )
            ),
            timeout=timeout_seconds,
        )

        return self.get_task(task_id)

    def shutdown(self) -> None:
        """Clean shutdown of all background observers."""
        with self._lock:
            for w in self._watchers.values():
                w.stop()
            self._watchers.clear()

            for pm in self._port_monitors.values():
                pm.stop()
            self._port_monitors.clear()

        self.event_bus.shutdown()


# Shared global TaskManager instance
task_manager = TaskManager()
