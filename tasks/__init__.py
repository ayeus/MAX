"""Tasks subsystem for MAX."""

from .models import TaskState, TaskType, ManagedTask, generate_task_id
from .persistence import save_task, get_task, list_tasks, reconcile_orphan_tasks, is_os_process_alive
from .supervisor import ProcessSupervisor
from .watchers import DirectoryWatcher, PortWatcher
from .manager import TaskManager, task_manager

__all__ = [
    "TaskState",
    "TaskType",
    "ManagedTask",
    "generate_task_id",
    "save_task",
    "get_task",
    "list_tasks",
    "reconcile_orphan_tasks",
    "is_os_process_alive",
    "ProcessSupervisor",
    "DirectoryWatcher",
    "PortWatcher",
    "TaskManager",
    "task_manager",
]
