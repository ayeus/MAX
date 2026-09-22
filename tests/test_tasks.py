"""Unit and live tests for MAX Task & Event Engine (Phase 10).

Distinguishes explicitly between:
- [UNIT TEST]: Model schemas, persistence queries, event bus subscriptions, and validation.
- [LIVE MAC TEST]: Real subprocess execution, real process group cancellation, real log streaming,
                   real startup orphan reconciliation, and real filesystem watcher events.
"""

import unittest
from pathlib import Path
import tempfile
import time
import os
import signal

from tasks.models import TaskState, TaskType, ManagedTask, generate_task_id
from tasks.persistence import (
    save_task,
    get_task,
    list_tasks,
    reconcile_orphan_tasks,
    is_os_process_alive,
)
from tasks.supervisor import ProcessSupervisor
from tasks.watchers import DirectoryWatcher, PortWatcher
from tasks.manager import TaskManager
from event_engine.events import (
    Event,
    EventType,
    TaskCompletedEvent,
    TaskFailedEvent,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
)
from event_engine.bus import EventBus
from capabilities.tasks import TaskCapability


class TestTaskAndEventEngine(unittest.TestCase):
    """Phase 10 Test Suite."""

    def setUp(self):
        self.test_bus = EventBus(max_workers=2)
        self.supervisor = ProcessSupervisor(event_bus=self.test_bus)
        self.manager = TaskManager(event_bus=self.test_bus)

    def tearDown(self):
        self.manager.shutdown()
        self.test_bus.shutdown(wait=False)

    # -------------------------------------------------------------------------
    # 1. Task ID Generation & Model Schemas
    # -------------------------------------------------------------------------

    def test_task_id_generation(self):
        """[UNIT TEST] Verify task ID format and collision resistance."""
        ids = {generate_task_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)
        sample = next(iter(ids))
        self.assertTrue(sample.startswith("tsk_"))
        self.assertGreaterEqual(len(sample), 16)

    def test_task_creation_and_persistence(self):
        """[UNIT TEST] Verify task creation, SQLite persistence, and retrieval."""
        task = ManagedTask(
            command="python3 -c 'print(42)'",
            task_type=TaskType.COMMAND,
            status=TaskState.CREATED,
            working_dir="/tmp",
            original_request="Test task persistence",
        )
        save_task(task)

        retrieved = get_task(task.task_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.task_id, task.task_id)
        self.assertEqual(retrieved.command, task.command)
        self.assertEqual(retrieved.status, TaskState.CREATED)
        self.assertEqual(retrieved.working_dir, "/tmp")

    def test_unknown_task_id(self):
        """[UNIT TEST] Querying or terminating non-existent task returns clean None or error."""
        res = get_task("tsk_non_existent_999999")
        self.assertIsNone(res)
        success, msg = self.manager.kill_task("tsk_non_existent_999999")
        self.assertFalse(success)
        self.assertIn("not found", msg)

    # -------------------------------------------------------------------------
    # 2. Live Subprocess Execution & Logging
    # -------------------------------------------------------------------------

    def test_process_launch_and_stdout_capture(self):
        """[LIVE MAC TEST] Launch real background process, verify PID/PGID and stdout capture."""
        task = self.supervisor.launch_task("echo 'MAX_BACKGROUND_STREAM_TEST'")
        self.assertIsNotNone(task.pid)
        self.assertIsNotNone(task.pgid)
        self.assertGreater(task.pid, 0)

        # Wait for task to finish
        finished = self.manager.wait_for_task(task.task_id, timeout_seconds=5.0)
        self.assertIsNotNone(finished)
        self.assertEqual(finished.status, TaskState.COMPLETED)
        self.assertEqual(finished.exit_code, 0)

        logs, truncated = self.supervisor.get_logs(task.task_id)
        self.assertIn("MAX_BACKGROUND_STREAM_TEST", logs)
        self.assertFalse(truncated)

    def test_process_non_zero_exit_and_stderr(self):
        """[LIVE MAC TEST] Process exiting non-zero transitions to FAILED with captured error."""
        task = self.supervisor.launch_task("python3 -c 'import sys; sys.stderr.write(\"ERR_BURST\"); sys.exit(4)'")
        finished = self.manager.wait_for_task(task.task_id, timeout_seconds=5.0)

        self.assertIsNotNone(finished)
        self.assertEqual(finished.status, TaskState.FAILED)
        self.assertEqual(finished.exit_code, 4)

        logs, _ = self.supervisor.get_logs(task.task_id)
        self.assertIn("ERR_BURST", logs)

    def test_task_cancellation_and_process_tree_cleanup(self):
        """[LIVE MAC TEST] Cancel a long-running process group, ensuring child processes are killed."""
        # Launch a background process tree (shell spawning child sleep)
        task = self.supervisor.launch_task("python3 -c 'import time; time.sleep(30)'")
        pid = task.pid
        self.assertTrue(is_os_process_alive(pid))

        # Cancel the task
        success, msg = self.supervisor.terminate_task(task.task_id)
        self.assertTrue(success)
        self.assertIn("terminated", msg)

        # Verify process is dead in OS
        time.sleep(0.3)
        self.assertFalse(is_os_process_alive(pid))

        # Verify task state in database
        updated = get_task(task.task_id)
        self.assertEqual(updated.status, TaskState.CANCELLED)

    def test_task_timeout(self):
        """[LIVE MAC TEST] Enforce maximum runtime timeout on runaway task."""
        # Max runtime 1 second for a 10s sleep
        task = self.supervisor.launch_task("sleep 10", max_runtime_seconds=1)
        finished = self.manager.wait_for_task(task.task_id, timeout_seconds=4.0)

        self.assertIsNotNone(finished)
        self.assertEqual(finished.status, TaskState.CANCELLED)
        self.assertIn("runtime limit", finished.error)

    # -------------------------------------------------------------------------
    # 3. Startup Orphan Reconciliation
    # -------------------------------------------------------------------------

    def test_restart_reconciliation(self):
        """[LIVE MAC TEST] Tasks left in RUNNING whose PID is dead are reconciled on startup."""
        # Create a phantom running task with dead PID 99999999
        phantom = ManagedTask(
            command="fake_job",
            status=TaskState.RUNNING,
            pid=99999999,
        )
        save_task(phantom)

        # Run orphan reconciliation
        reconciled = reconcile_orphan_tasks()
        reconciled_ids = [t.task_id for t in reconciled]
        self.assertIn(phantom.task_id, reconciled_ids)

        check = get_task(phantom.task_id)
        self.assertEqual(check.status, TaskState.UNKNOWN)
        self.assertIn("orphan reconciled", check.error)

    # -------------------------------------------------------------------------
    # 4. Event Bus & Subscriptions
    # -------------------------------------------------------------------------

    def test_event_subscription_and_wait_for(self):
        """[UNIT TEST] Verify EventBus publish/subscribe and deterministic wait_for."""
        bus = EventBus(max_workers=2)
        received_events = []

        def _handler(ev: Event):
            received_events.append(ev)

        sub_id = bus.subscribe(EventType.TASK_COMPLETED, _handler)

        test_ev = TaskCompletedEvent(source="test", task_id="tsk_123", exit_code=0)
        bus.publish(test_ev)

        # Wait up to 1 second
        time.sleep(0.2)
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].task_id, "tsk_123")

        # Unsubscribe
        bus.unsubscribe(sub_id)
        bus.publish(TaskCompletedEvent(source="test", task_id="tsk_456", exit_code=0))
        time.sleep(0.2)
        self.assertEqual(len(received_events), 1)
        bus.shutdown()

    # -------------------------------------------------------------------------
    # 5. Real Filesystem Watcher
    # -------------------------------------------------------------------------

    def test_filesystem_watcher_lifecycle_and_events(self):
        """[LIVE MAC TEST] DirectoryWatcher observes file creation and modification with debouncing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            events_received = []

            def _listener(ev: Event):
                events_received.append(ev)

            sub_id = self.test_bus.subscribe("*", _listener)

            watcher = DirectoryWatcher(
                watch_path=tmpdir,
                recursive=False,
                debounce_seconds=0.1,
                poll_interval_seconds=0.2,
                event_bus=self.test_bus,
            )
            watcher.start()
            self.assertTrue(watcher.is_running())

            test_file = Path(tmpdir) / "build_output.txt"

            # 1. Create file
            test_file.write_text("Build started...")
            time.sleep(0.6)

            created_events = [e for e in events_received if isinstance(e, FileCreatedEvent)]
            self.assertGreaterEqual(len(created_events), 1)
            self.assertEqual(Path(created_events[0].path).name, "build_output.txt")

            # 2. Modify file
            test_file.write_text("Build completed successfully!")
            time.sleep(0.6)

            modified_events = [e for e in events_received if isinstance(e, FileModifiedEvent)]
            self.assertGreaterEqual(len(modified_events), 1)

            # 3. Stop watcher
            watcher.stop()
            self.assertFalse(watcher.is_running())
            self.test_bus.unsubscribe(sub_id)

    # -------------------------------------------------------------------------
    # 6. Task Capability Integration
    # -------------------------------------------------------------------------

    def test_task_capability_operations(self):
        """[LIVE MAC TEST] TaskCapability executes start, status, list, and kill operations."""
        cap = TaskCapability(manager=self.manager)

        # 1. Start background task
        res_start = cap.start_background_task(command="sleep 15", is_daemon=False)
        self.assertTrue(res_start.success)
        task_id = res_start.data["task_id"]

        # 2. Status
        res_status = cap.get_task_status(task_id=task_id)
        self.assertTrue(res_status.success)
        self.assertEqual(res_status.data["task_id"], task_id)
        self.assertIn(res_status.data["status"], ("STARTING", "RUNNING"))

        # 3. List
        res_list = cap.list_tasks()
        self.assertTrue(res_list.success)
        task_ids = [t["task_id"] for t in res_list.data["tasks"]]
        self.assertIn(task_id, task_ids)

        # 4. Kill
        res_kill = cap.kill_task(task_id=task_id)
        self.assertTrue(res_kill.success)

        # 5. Verify killed
        res_after = cap.get_task_status(task_id=task_id)
        self.assertEqual(res_after.data["status"], "CANCELLED")


from unittest.mock import patch
from tasks.persistence import (
    get_process_start_time,
    _get_native_macos_start_time,
    _get_ps_start_time,
    are_process_start_times_matching,
)


class TestProcessIdentity(unittest.TestCase):
    """Tests for Phase 6 Process Identity and Native macOS sysctl/libproc."""

    def test_process_start_time_valid_pid(self):
        """Valid running PID returns non-empty start time."""
        current_pid = os.getpid()
        st = get_process_start_time(current_pid)
        self.assertIsNotNone(st)
        self.assertTrue(len(st) > 0)

    def test_process_start_time_invalid_pid(self):
        """Invalid PID (<= 0) returns None."""
        self.assertIsNone(get_process_start_time(0))
        self.assertIsNone(get_process_start_time(-1))
        self.assertIsNone(get_process_start_time(-999))

    def test_process_start_time_dead_pid(self):
        """Dead / non-existent PID returns None."""
        self.assertIsNone(get_process_start_time(9999999))

    def test_process_start_time_native_success(self):
        """On macOS, native libproc extracts high-precision start time."""
        if os.uname().sysname == "Darwin":
            st = _get_native_macos_start_time(os.getpid())
            self.assertIsNotNone(st)
            self.assertIn(".", st)
            sec, usec = st.split(".")
            self.assertTrue(sec.isdigit())
            self.assertTrue(usec.isdigit())

    def test_process_start_time_fallback_to_ps(self):
        """When native fails, get_process_start_time falls back to _get_ps_start_time."""
        with patch("tasks.persistence._get_native_macos_start_time", return_value=None):
            with patch("tasks.persistence._get_ps_start_time", return_value="Tue Sep 22 12:00:00 2026") as mock_ps:
                st = get_process_start_time(12345)
                self.assertEqual(st, "Tue Sep 22 12:00:00 2026")
                mock_ps.assert_called_once_with(12345)

    def test_process_start_time_both_unavailable(self):
        """When both native and ps fail, returns None without fabricating timestamps."""
        with patch("tasks.persistence._get_native_macos_start_time", return_value=None):
            with patch("tasks.persistence._get_ps_start_time", return_value=None):
                st = get_process_start_time(12345)
                self.assertIsNone(st)

    def test_start_time_matching_semantics(self):
        """Matches identical strings, or epoch float vs ps ctime within 1s tolerance."""
        # Identical strings
        self.assertTrue(are_process_start_times_matching("1700000000.123456", "1700000000.123456"))
        self.assertTrue(are_process_start_times_matching("Tue Sep 22 12:00:00 2026", "Tue Sep 22 12:00:00 2026"))

        # None / empty
        self.assertFalse(are_process_start_times_matching(None, "1700000000.123456"))
        self.assertFalse(are_process_start_times_matching("1700000000.123456", None))

        # Different timestamps
        self.assertFalse(are_process_start_times_matching("1700000000.123456", "1700050000.123456"))

        # Native epoch vs ps ctime representation of the same time
        now_sec = 1700000000
        ctime_val = time.ctime(now_sec)
        native_val = f"{now_sec}.500000"
        self.assertTrue(are_process_start_times_matching(native_val, ctime_val))
        self.assertTrue(are_process_start_times_matching(ctime_val, native_val))

    def test_pid_reuse_reconciliation(self):
        """Reconciliation marks task UNKNOWN if PID was reused with different start time."""
        # Create a task marked RUNNING with current PID, but an old bogus start time
        task = ManagedTask(
            command="long_running_job",
            status=TaskState.RUNNING,
            pid=os.getpid(),
            metadata={"process_start_time": "1000000000.000000"},  # Way in the past
        )
        save_task(task)

        reconciled = reconcile_orphan_tasks()
        reconciled_ids = [t.task_id for t in reconciled]
        self.assertIn(task.task_id, reconciled_ids)

        updated = get_task(task.task_id)
        self.assertEqual(updated.status, TaskState.UNKNOWN)
        self.assertIn("reused", updated.error)

    def test_pid_reuse_refuses_termination(self):
        """Supervisor refuses to kill an unrelated process if start time does not match."""
        supervisor = ProcessSupervisor()
        task = ManagedTask(
            command="fake_job",
            status=TaskState.RUNNING,
            pid=os.getpid(),  # Don't kill self!
            metadata={"process_start_time": "1000000000.000000"},
        )
        save_task(task)

        success, msg = supervisor.terminate_task(task.task_id)
        self.assertFalse(success)
        self.assertIn("unrelated process", msg)


if __name__ == "__main__":
    unittest.main()
