"""Thread-safe event bus for publishing, subscribing, and deterministic event waiting in MAX."""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
import time
import uuid
from typing import Callable, Optional, Union
from event_engine.events import Event, EventType

logger = logging.getLogger(__name__)


class Subscription:
    def __init__(
        self,
        sub_id: str,
        event_type: Union[EventType, str],
        callback: Callable[[Event], None],
        filter_fn: Optional[Callable[[Event], bool]] = None,
    ):
        self.sub_id = sub_id
        self.event_type = str(event_type.value if isinstance(event_type, EventType) else event_type)
        self.callback = callback
        self.filter_fn = filter_fn


class EventBus:
    """Central event hub coordinating asynchronous notifications across MAX subsystems."""

    def __init__(self, max_workers: int = 4):
        self._lock = threading.RLock()
        self._subscriptions: dict[str, Subscription] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="max-event-bus")
        self._history: list[Event] = []
        self._max_history = 500

    def subscribe(
        self,
        event_type: Union[EventType, str],
        callback: Callable[[Event], None],
        filter_fn: Optional[Callable[[Event], bool]] = None,
    ) -> str:
        """Register a callback for a specific event type, with optional predicate filtering."""
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        sub = Subscription(sub_id, event_type, callback, filter_fn)
        with self._lock:
            self._subscriptions[sub_id] = sub
        return sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Remove an active subscription."""
        with self._lock:
            return self._subscriptions.pop(sub_id, None) is not None

    def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers asynchronously."""
        with self._lock:
            # Store in bounded circular history
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)

            # Match subscribers
            event_type_str = str(event.event_type.value if isinstance(event.event_type, EventType) else event.event_type)
            matching = [
                sub for sub in self._subscriptions.values()
                if (sub.event_type == "*" or sub.event_type == event_type_str)
            ]

        for sub in matching:
            try:
                if sub.filter_fn is None or sub.filter_fn(event):
                    self._executor.submit(self._safe_invoke, sub.callback, event)
            except Exception as e:
                logger.error(f"Error evaluating filter on subscription {sub.sub_id}: {e}")

    def _safe_invoke(self, callback: Callable[[Event], None], event: Event) -> None:
        try:
            callback(event)
        except Exception as e:
            logger.error(f"Unhandled exception in event callback: {e}", exc_info=True)

    def wait_for(
        self,
        event_type: Union[EventType, str],
        filter_fn: Optional[Callable[[Event], bool]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Event]:
        """Block the calling thread deterministically until a matching event is published or timeout expires.
        
        Zero LLM consumption during wait. Uses standard threading.Event synchronization.
        """
        ready = threading.Event()
        captured_event: list[Event] = []

        def _handler(ev: Event):
            captured_event.append(ev)
            ready.set()

        sub_id = self.subscribe(event_type, _handler, filter_fn)
        try:
            success = ready.wait(timeout=timeout)
            if success and captured_event:
                return captured_event[0]
            return None
        finally:
            self.unsubscribe(sub_id)

    def get_history(self, task_id: Optional[str] = None, limit: int = 50) -> list[Event]:
        """Retrieve recent events from the in-memory circular history."""
        with self._lock:
            if task_id:
                return [e for e in self._history if e.task_id == task_id][-limit:]
            return list(self._history[-limit:])

    def shutdown(self, wait: bool = False) -> None:
        """Shut down executor threads cleanly."""
        self._executor.shutdown(wait=wait)


# Shared global EventBus instance
global_event_bus = EventBus()
