"""In-process synchronous event bus — ADR-0011.

Publisher and its handlers run synchronously, in order, in the caller's
stack (so they share one transaction). No async, no queue.
"""

from dataclasses import dataclass

from books.platform.events import EventBus


@dataclass(frozen=True)
class Pinged:
    n: int


def test_handler_receives_published_event():
    seen: list[int] = []
    bus = EventBus()
    bus.subscribe(Pinged, lambda e: seen.append(e.n))

    bus.publish(Pinged(7))

    assert seen == [7]


def test_handlers_run_synchronously_in_subscription_order():
    order: list[str] = []
    bus = EventBus()
    bus.subscribe(Pinged, lambda e: order.append("first"))
    bus.subscribe(Pinged, lambda e: order.append("second"))

    bus.publish(Pinged(1))

    assert order == ["first", "second"]


def test_unrelated_event_type_is_not_delivered():
    seen: list[int] = []
    bus = EventBus()
    bus.subscribe(Pinged, lambda e: seen.append(e.n))

    bus.publish("not an event")  # type: ignore[arg-type]

    assert seen == []
