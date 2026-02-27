"""Event emitter implementation — in-process pub/sub for status broadcasting."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from rigovo.domain.interfaces.event_emitter import EventEmitter

logger = logging.getLogger(__name__)

Callback = Callable[[dict[str, Any]], None]


class InProcessEventEmitter(EventEmitter):
    """
    Simple in-process event emitter using callbacks.

    Subscribers register callbacks for event types. When an event is
    emitted, all matching callbacks fire synchronously.

    Used by: terminal UI (display status), cloud sync (push metadata),
    audit logger (record actions).
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callback]] = defaultdict(list)
        self._global_listeners: list[Callback] = []

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        event = {"type": event_type, **data}
        for cb in self._global_listeners:
            try:
                cb(event)
            except Exception:
                logger.exception("Global event listener error for %s", event_type)
        for cb in self._listeners.get(event_type, []):
            try:
                cb(event)
            except Exception:
                logger.exception("Event listener error for %s", event_type)

    def on(self, event_type: str, callback: Callback) -> None:
        self._listeners[event_type].append(callback)

    def off(self, event_type: str, callback: Callback) -> None:
        listeners = self._listeners.get(event_type, [])
        if callback in listeners:
            listeners.remove(callback)

    def on_all(self, callback: Callback) -> None:
        """Subscribe to ALL events regardless of type."""
        self._global_listeners.append(callback)

    def clear(self) -> None:
        """Remove all listeners."""
        self._listeners.clear()
        self._global_listeners.clear()
