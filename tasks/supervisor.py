"""Process supervisor for launching, monitoring, and terminating background process trees in MAX."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any, Optional
from app.config import settings
from event_engine.bus import EventBus, global_event_bus
from event_engine.events import (
    ProcessStartedEvent,
    ProcessExitedEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
    TaskCancelledEvent,
)
from tasks.models import ManagedTask, TaskState, TaskType
from tasks.persistence import (
    save_task,
    get_task,
    is_os_process_alive,
    get_process_start_time,
    are_process_start_times_matching,
)

logger = logging.getLogger(__name__)


class ProcessSupervisor:
    """Supervises background child processes and their process trees on macOS."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or global_event_bus
        self._lock = threading.RLock()
        self._active_processes: dict[str, subprocess.Popen] = {}
        self._monitor_threads: dict[str, threading.Thread] = {}
        self._ensure_log_directory()

    def _ensure_log_directory(self) -> Path:
        log_dir = settings.base_dir / "logs" / "tasks"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def get_log_path(self, task_id: str) -> Path:
        return self._ensure_log_directory() / f"{task_id}.log"

    def launch_task(
        self,
        command: str,
        working_dir: Optional[str] = None,
        task_type: TaskType = TaskType.COMMAND,
        max_runtime_seconds: Optional[int] = None,
        original_request: Optional[str] = None,
        env_vars: Optional[dict[str, str]] = None,
    ) -> ManagedTask:
        """Launch a real background subprocess with its own process group and streaming log file."""
        cwd = working_dir or str(Path.cwd())
        task = ManagedTask(
            command=command,
            task_type=task_type,
            status=TaskState.STARTING,
            working_dir=cwd,
            original_request=original_request,
            max_runtime_seconds=max_runtime_seconds,
        )

        log_path = self.get_log_path(task.task_id)
        task.log_file = str(log_path)
        save_task(task)

        # Environment setup
        exec_env = os.environ.copy()
        if env_vars:
            exec_env.update(env_vars)

        try:
            log_file = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
            # Write initial log header
            log_file.write(f"=== MAX Task [{task.task_id}] Started: {datetime.now(timezone.utc).isoformat()} ===\n")
            log_file.write(f"Command: {command}\nWorking Dir: {cwd}\n\n")
            log_file.flush()

            # Launch process in a new process group (start_new_session=True)
            proc = subprocess.Popen(
                ["/bin/zsh", "-c", command],
                cwd=cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=exec_env,
            )

            task.pid = proc.pid
            try:
                task.pgid = os.getpgid(proc.pid)
            except Exception:
                task.pgid = proc.pid

            task.metadata["process_start_time"] = get_process_start_time(proc.pid)
            task.status = TaskState.RUNNING
            task.started_at = datetime.now(timezone.utc).isoformat()
            save_task(task)

            with self._lock:
                self._active_processes[task.task_id] = proc

            # Emit ProcessStartedEvent
            self.event_bus.publish(
                ProcessStartedEvent(
                    source="supervisor",
                    task_id=task.task_id,
                    pid=task.pid,
                    pgid=task.pgid,
                    command=command,
                )
            )

            # Spawn monitoring background thread
            t = threading.Thread(
                target=self._monitor_process,
                args=(task.task_id, proc, log_file, max_runtime_seconds),
                name=f"task-monitor-{task.task_id}",
                daemon=True,
            )
            with self._lock:
                self._monitor_threads[task.task_id] = t
            t.start()

            return task

        except Exception as e:
            task.status = TaskState.FAILED
            task.error = f"Failed to spawn background process: {str(e)}"
            task.finished_at = datetime.now(timezone.utc).isoformat()
            save_task(task)
            self.event_bus.publish(
                TaskFailedEvent(
                    source="supervisor",
                    task_id=task.task_id,
                    error=task.error,
                )
            )
            return task

    def _monitor_process(
        self,
        task_id: str,
        proc: subprocess.Popen,
        log_file: Any,
        max_runtime: Optional[int],
    ) -> None:
        """Background thread monitoring process termination or timeout without polling the LLM."""
        start_time = time.time()

        try:
            while proc.poll() is None:
                # Check runtime limit
                if max_runtime and (time.time() - start_time) > max_runtime:
                    logger.warning(f"Task {task_id} exceeded max runtime of {max_runtime}s. Terminating.")
                    self.terminate_task(task_id, reason=f"Exceeded maximum runtime limit of {max_runtime}s")
                    try:
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
                    return

                time.sleep(0.2)

            # Process exited
            exit_code = proc.returncode
            duration_ms = (time.time() - start_time) * 1000.0
            finish_iso = datetime.now(timezone.utc).isoformat()

            # Finalize log file
            try:
                log_file.write(f"\n=== MAX Task [{task_id}] Finished with Exit Code {exit_code} at {finish_iso} ===\n")
                log_file.flush()
            except Exception:
                pass

            task = get_task(task_id)
            if not task:
                return

            # Check if it was cancelled during termination
            if task.status == TaskState.CANCELLED:
                return

            task.exit_code = exit_code
            task.finished_at = finish_iso

            if exit_code == 0:
                task.status = TaskState.COMPLETED
                save_task(task)
                self.event_bus.publish(
                    TaskCompletedEvent(
                        source="supervisor",
                        task_id=task_id,
                        exit_code=0,
                        duration_ms=duration_ms,
                    )
                )
            else:
                task.status = TaskState.FAILED
                task.error = f"Process exited with non-zero code {exit_code}"
                save_task(task)
                self.event_bus.publish(
                    TaskFailedEvent(
                        source="supervisor",
                        task_id=task_id,
                        exit_code=exit_code,
                        error=task.error,
                        duration_ms=duration_ms,
                    )
                )

            self.event_bus.publish(
                ProcessExitedEvent(
                    source="supervisor",
                    task_id=task_id,
                    pid=task.pid or 0,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )
            )

        except Exception as e:
            logger.error(f"Error in monitor thread for task {task_id}: {e}")
        finally:
            try:
                log_file.close()
            except Exception:
                pass
            with self._lock:
                self._active_processes.pop(task_id, None)
                self._monitor_threads.pop(task_id, None)

    def terminate_task(self, task_id: str, reason: str = "User requested cancellation") -> tuple[bool, str]:
        """Terminate a managed task and its full process tree safely using SIGTERM then SIGKILL."""
        task = get_task(task_id)
        if not task:
            return False, f"Task '{task_id}' not found."

        if not task.is_active and not (task.pid and is_os_process_alive(task.pid)):
            return False, f"Task '{task_id}' is not active (current status: {task.status.value})."

        target_pid = task.pid
        target_pgid = task.pgid

        if not target_pid:
            task.status = TaskState.CANCELLED
            save_task(task)
            return True, f"Task '{task_id}' had no PID and was marked CANCELLED."

        # Verify process identity to avoid killing a recycled PID
        if task.metadata.get("process_start_time"):
            current_start = get_process_start_time(target_pid)
            if current_start and not are_process_start_times_matching(current_start, task.metadata["process_start_time"]):
                return False, f"PID {target_pid} belongs to an unrelated process (start time mismatch). Refusing to terminate."

        # 1. Send SIGTERM to process group
        try:
            if target_pgid:
                os.killpg(target_pgid, signal.SIGTERM)
            else:
                os.kill(target_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"Error sending SIGTERM to task {task_id}: {e}")

        # 2. Grace period for clean termination
        settled = False
        for _ in range(12):  # up to 2.4s
            time.sleep(0.2)
            if not is_os_process_alive(target_pid):
                settled = True
                break

        # 3. If still running, force SIGKILL to process group
        if not settled:
            try:
                if target_pgid:
                    os.killpg(target_pgid, signal.SIGKILL)
                else:
                    os.kill(target_pid, signal.SIGKILL)
            except Exception:
                pass

        task.status = TaskState.CANCELLED
        task.finished_at = datetime.now(timezone.utc).isoformat()
        task.error = reason
        save_task(task)

        with self._lock:
            self._active_processes.pop(task_id, None)

        self.event_bus.publish(
            TaskCancelledEvent(
                source="supervisor",
                task_id=task_id,
                reason=reason,
            )
        )

        return True, f"Task '{task_id}' (PID {target_pid}, PGID {target_pgid}) terminated safely."

    def get_logs(self, task_id: str, tail_lines: int = 100) -> tuple[str, bool]:
        """Read bounded log output from the task's dedicated log file."""
        log_path = self.get_log_path(task_id)
        if not log_path.exists():
            return f"Log file for task '{task_id}' does not exist.", False

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if len(lines) > tail_lines:
                content = "".join(lines[-tail_lines:])
                return content, True
            else:
                return "".join(lines), False
        except Exception as e:
            return f"Error reading log file: {str(e)}", False
