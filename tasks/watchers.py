"""Real filesystem and service/port watchers for MAX event engine."""

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import socket
import threading
import time
from typing import Callable, Optional
from event_engine.bus import EventBus, global_event_bus
from event_engine.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    ServiceStatusChangedEvent,
)

logger = logging.getLogger(__name__)


class DirectoryWatcher:
    """Monitors directory paths for file creation, modification, and deletion with event debouncing."""

    def __init__(
        self,
        watch_path: str,
        recursive: bool = True,
        debounce_seconds: float = 0.3,
        poll_interval_seconds: float = 0.5,
        event_bus: Optional[EventBus] = None,
        task_id: Optional[str] = None,
    ):
        self.watch_path = Path(watch_path).resolve()
        self.recursive = recursive
        self.debounce_seconds = debounce_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.event_bus = event_bus or global_event_bus
        self.task_id = task_id

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file_snapshots: dict[str, tuple[float, int]] = {}  # path -> (mtime, size)
        self._pending_events: dict[str, float] = {}              # path -> last_event_time
        self._lock = threading.Lock()

    def _scan_directory(self) -> dict[str, tuple[float, int]]:
        """Collect current state of files under the watched path."""
        snapshot = {}
        if not self.watch_path.exists():
            return snapshot

        if self.watch_path.is_file():
            try:
                st = self.watch_path.stat()
                snapshot[str(self.watch_path)] = (st.st_mtime, st.st_size)
            except Exception:
                pass
            return snapshot

        try:
            pattern = "**/*" if self.recursive else "*"
            for p in self.watch_path.glob(pattern):
                try:
                    if p.is_file() and not p.name.startswith("."):
                        st = p.stat()
                        snapshot[str(p)] = (st.st_mtime, st.st_size)
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Error scanning directory {self.watch_path}: {e}")

        return snapshot

    def start(self) -> None:
        """Start the background filesystem observer thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._file_snapshots = self._scan_directory()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"dir-watcher-{self.watch_path.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop watching and terminate the worker thread cleanly."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.poll_interval_seconds)
            if self._stop_event.is_set():
                break

            current_snapshot = self._scan_directory()
            now = time.time()

            # 1. Detect Created and Modified files
            for path_str, (mtime, size) in current_snapshot.items():
                if path_str not in self._file_snapshots:
                    # File Created
                    if self._is_debounced(path_str, now):
                        self.event_bus.publish(
                            FileCreatedEvent(
                                source="watcher",
                                task_id=self.task_id,
                                path=path_str,
                            )
                        )
                else:
                    prev_mtime, prev_size = self._file_snapshots[path_str]
                    if mtime != prev_mtime or size != prev_size:
                        # File Modified
                        if self._is_debounced(path_str, now):
                            self.event_bus.publish(
                                FileModifiedEvent(
                                    source="watcher",
                                    task_id=self.task_id,
                                    path=path_str,
                                )
                            )

            # 2. Detect Deleted files
            for path_str in self._file_snapshots:
                if path_str not in current_snapshot:
                    if self._is_debounced(path_str, now):
                        self.event_bus.publish(
                            FileDeletedEvent(
                                source="watcher",
                                task_id=self.task_id,
                                path=path_str,
                            )
                        )

            self._file_snapshots = current_snapshot

    def _is_debounced(self, path: str, now: float) -> bool:
        with self._lock:
            last = self._pending_events.get(path, 0.0)
            if (now - last) >= self.debounce_seconds:
                self._pending_events[path] = now
                return True
            return False


class PortWatcher:
    """Monitors whether a specific TCP port is listening and emits state transition events."""

    def __init__(
        self,
        port: int,
        host: str = "127.0.0.1",
        service_name: Optional[str] = None,
        poll_interval_seconds: float = 1.0,
        event_bus: Optional[EventBus] = None,
        task_id: Optional[str] = None,
    ):
        self.port = port
        self.host = host
        self.service_name = service_name or f"Port-{port}"
        self.poll_interval_seconds = poll_interval_seconds
        self.event_bus = event_bus or global_event_bus
        self.task_id = task_id

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_state: Optional[bool] = None

    def is_port_open(self) -> bool:
        """Check if TCP port accepts connections."""
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def start(self) -> None:
        """Start the background port observer thread."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._last_state = self.is_port_open()
        self._thread = threading.Thread(
            target=self._run_loop,
            name=f"port-watcher-{self.port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop monitoring the port."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.poll_interval_seconds)
            if self._stop_event.is_set():
                break

            current_state = self.is_port_open()
            if self._last_state is not None and current_state != self._last_state:
                # State transition occurred
                self.event_bus.publish(
                    ServiceStatusChangedEvent(
                        source="port_watcher",
                        task_id=self.task_id,
                        service_name=self.service_name,
                        port=self.port,
                        is_listening=current_state,
                    )
                )

            self._last_state = current_state
