"""Event emitter interface — decoupled observer pattern for status broadcasting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EventEmitter(ABC):
    """
    Observer Pattern: graph nodes emit events through this interface.
    Terminal UI subscribes to display real-time status.
    Cloud sync subscribes to push metadata.

    Decoupled — the graph doesn't know who's listening.
    """

    @abstractmethod
    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: Event name (e.g. 'agent_started', 'gate_results', 'task_complete').
            data: Event payload.
        """
        ...

    @abstractmethod
    def on(self, event_type: str, callback: Any) -> None:
        """
        Subscribe to events of a specific type.

        Args:
            event_type: Event name to listen for.
            callback: Callable invoked when event fires.
        """
        ...

    @abstractmethod
    def off(self, event_type: str, callback: Any) -> None:
        """Unsubscribe a callback from an event type."""
        ...
