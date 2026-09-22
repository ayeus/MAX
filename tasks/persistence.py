"""SQLite persistence and startup orphan recovery for managed tasks in MAX."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Optional
from app.config import settings
from tasks.models import ManagedTask, TaskState, TaskType


def get_db_connection() -> sqlite3.Connection:
    """Connect to SQLite database and return connection."""
    db_path = settings.memory_db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_tasks_schema() -> None:
    """Ensure managed_tasks table exists in SQLite database."""
    conn = get_db_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS managed_tasks (
                task_id TEXT PRIMARY KEY NOT NULL,
                command TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                pid INTEGER,
                pgid INTEGER,
                working_dir TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                error TEXT,
                log_file TEXT,
                original_request TEXT,
                max_runtime_seconds INTEGER,
                metadata_json TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON managed_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON managed_tasks(created_at);
            """)
    finally:
        conn.close()


def save_task(task: ManagedTask) -> None:
    """Insert or update a managed task in the database."""
    init_tasks_schema()
    conn = get_db_connection()
    meta_json = json.dumps(task.metadata or {})
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO managed_tasks (
                    task_id, command, task_type, status, pid, pgid,
                    working_dir, created_at, started_at, finished_at,
                    exit_code, error, log_file, original_request,
                    max_runtime_seconds, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    pid = excluded.pid,
                    pgid = excluded.pgid,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    exit_code = excluded.exit_code,
                    error = excluded.error,
                    log_file = excluded.log_file,
                    metadata_json = excluded.metadata_json;
                """,
                (
                    task.task_id,
                    task.command,
                    task.task_type.value,
                    task.status.value,
                    task.pid,
                    task.pgid,
                    task.working_dir,
                    task.created_at,
                    task.started_at,
                    task.finished_at,
                    task.exit_code,
                    task.error,
                    task.log_file,
                    task.original_request,
                    task.max_runtime_seconds,
                    meta_json,
                ),
            )
    finally:
        conn.close()


def _row_to_task(row: sqlite3.Row) -> ManagedTask:
    meta = {}
    if row["metadata_json"]:
        try:
            meta = json.loads(row["metadata_json"])
        except Exception:
            pass

    return ManagedTask(
        task_id=row["task_id"],
        command=row["command"],
        task_type=TaskType(row["task_type"]),
        status=TaskState(row["status"]),
        pid=row["pid"],
        pgid=row["pgid"],
        working_dir=row["working_dir"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        exit_code=row["exit_code"],
        error=row["error"],
        log_file=row["log_file"] or "",
        original_request=row["original_request"],
        max_runtime_seconds=row["max_runtime_seconds"],
        metadata=meta,
    )


def get_task(task_id: str) -> Optional[ManagedTask]:
    """Retrieve task by unique ID."""
    init_tasks_schema()
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM managed_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row:
            return _row_to_task(row)
        return None
    finally:
        conn.close()


def list_tasks(status: Optional[TaskState] = None, limit: int = 50) -> list[ManagedTask]:
    """List managed tasks ordered by creation date descending."""
    init_tasks_schema()
    conn = get_db_connection()
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM managed_tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM managed_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        return [_row_to_task(r) for r in rows]
    finally:
        conn.close()


import ctypes
import ctypes.util
import sys
import time

_PROC_PIDTBSDINFO = 3
_MAXCOMLEN = 16


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * _MAXCOMLEN),
        ("pbi_name", ctypes.c_char * (2 * _MAXCOMLEN)),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


_libproc_handle = None
_libproc_initialized = False


def _get_libproc():
    global _libproc_handle, _libproc_initialized
    if not _libproc_initialized:
        _libproc_initialized = True
        if sys.platform == "darwin":
            try:
                lib_path = ctypes.util.find_library("proc")
                if lib_path:
                    _libproc_handle = ctypes.CDLL(lib_path)
                elif os.path.exists("/usr/lib/libproc.dylib"):
                    _libproc_handle = ctypes.CDLL("/usr/lib/libproc.dylib")
            except Exception:
                _libproc_handle = None
    return _libproc_handle


def _get_native_macos_start_time(pid: int) -> Optional[str]:
    """Retrieve process start time via native macOS libproc API."""
    if pid <= 0 or sys.platform != "darwin":
        return None
    lib = _get_libproc()
    if not lib or not hasattr(lib, "proc_pidinfo"):
        return None
    try:
        info = _ProcBsdInfo()
        ret = lib.proc_pidinfo(
            pid,
            _PROC_PIDTBSDINFO,
            0,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if ret == ctypes.sizeof(info) and info.pbi_start_tvsec > 0:
            return f"{info.pbi_start_tvsec}.{info.pbi_start_tvusec:06d}"
    except Exception:
        pass
    return None


def _get_ps_start_time(pid: int) -> Optional[str]:
    """Fallback: retrieve process start time string via /bin/ps."""
    if pid <= 0:
        return None
    try:
        res = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return None


def are_process_start_times_matching(t1: Optional[str], t2: Optional[str]) -> bool:
    """Compare two process start time representations (native epoch or ps ctime)."""
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    try:
        # Check if one is epoch float and one is ctime
        if "." in t1 and any(c.isalpha() for c in t2):
            sec1 = int(float(t1))
            sec2 = int(time.mktime(time.strptime(t2)))
            return abs(sec1 - sec2) <= 1
        elif "." in t2 and any(c.isalpha() for c in t1):
            sec1 = int(float(t2))
            sec2 = int(time.mktime(time.strptime(t1)))
            return abs(sec1 - sec2) <= 1
    except Exception:
        pass
    return False


def get_process_start_time(pid: int) -> Optional[str]:
    """Get the start time string of an OS process for process identity verification.

    Order:
    1. Native macOS libproc API (returns high-precision epoch timestamp)
    2. /bin/ps fallback
    3. None when both fail or PID is invalid/dead.
    Never fabricates a timestamp.
    """
    if pid <= 0:
        return None
    native = _get_native_macos_start_time(pid)
    if native is not None:
        return native
    return _get_ps_start_time(pid)


def is_os_process_alive(pid: int) -> bool:
    """Check whether a PID is alive and active in macOS.

    Uses native os.kill(pid, 0) error checking with zombie status inspection.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False

    # Check if process is a zombie via ps fallback
    try:
        res = subprocess.run(
            ["/bin/ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if res.returncode == 0:
            state = res.stdout.strip()
            if state.startswith("Z"):
                return False
            return True
        return False
    except Exception:
        return True


def reconcile_orphan_tasks() -> list[ManagedTask]:
    """Reconcile persisted tasks against actual OS process table on MAX startup.

    Identifies tasks marked RUNNING/STARTING/WAITING whose processes no longer exist,
    or whose PID was recycled by another process, updating them to avoid ghost tasks.
    """
    init_tasks_schema()
    active_tasks = list_tasks()
    reconciled: list[ManagedTask] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for task in active_tasks:
        if task.status in (TaskState.STARTING, TaskState.RUNNING, TaskState.WAITING):
            if task.pid is None or not is_os_process_alive(task.pid):
                task.status = TaskState.UNKNOWN
                task.finished_at = now_iso
                task.error = "Process no longer alive on system startup (orphan reconciled)"
                save_task(task)
                reconciled.append(task)
            elif task.metadata.get("process_start_time"):
                curr_start = get_process_start_time(task.pid)
                if curr_start and not are_process_start_times_matching(curr_start, task.metadata.get("process_start_time")):
                    task.status = TaskState.UNKNOWN
                    task.finished_at = now_iso
                    task.error = "PID was reused by an unrelated process after MAX restart (reconciled)"
                    save_task(task)
                    reconciled.append(task)

    return reconciled
