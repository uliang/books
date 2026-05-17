"""In-process synchronous domain-event bus (ADR-0011).

A publisher and its subscribed handlers execute synchronously in the same
call stack, so they participate in the one transaction the use-case command
opened (ADR-0013). No async, no persisted log in v1.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable[[Any], None]) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        for handler in self._handlers.get(type(event), ()):
            handler(event)
