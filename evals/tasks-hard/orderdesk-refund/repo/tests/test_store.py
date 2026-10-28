import json
from pathlib import Path

import pytest
from orderdesk.errors import ConcurrencyError
from orderdesk.events import (
    Line,
    NoteAdded,
    OrderCancelled,
    OrderPlaced,
    OrderShipped,
    PaymentCaptured,
    from_record,
    to_record,
)
from orderdesk.store import JsonlEventStore, MemoryEventStore

AT = "2026-03-01T09:00:00Z"
SAMPLES = [
    OrderPlaced("ORD-0001", AT, "alice", "alice@example.com", (Line("MUG-01", 2, 950),)),
    PaymentCaptured("ORD-0001", AT, 1900, "card"),
    OrderShipped("ORD-0001", AT, "PostNL", "3S123"),
    OrderCancelled("ORD-0002", AT, "duplicate", 0),
    NoteAdded("ORD-0001", AT, "carla", "fragile"),
]


@pytest.mark.parametrize("ev", SAMPLES, ids=lambda ev: ev.type)
def test_every_event_survives_a_trip_through_json(ev) -> None:
    record = json.loads(json.dumps(to_record(ev)))
    assert record["type"] == ev.type
    assert from_record(record) == ev


def test_unknown_event_types_are_refused() -> None:
    with pytest.raises(ValueError, match="unknown event type"):
        from_record({"type": "order.teleported", "order_id": "ORD-0001", "at": AT})


def test_the_jsonl_store_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = JsonlEventStore(path)
    store.append("ORD-0001", SAMPLES[:2], expected_version=0)
    store.append("ORD-0001", SAMPLES[2:3], expected_version=2)

    reopened = JsonlEventStore(path)
    assert reopened.load("ORD-0001") == SAMPLES[:3]
    assert reopened.all_events() == SAMPLES[:3]
    assert reopened.order_ids() == ["ORD-0001"]


def test_appends_check_the_expected_version() -> None:
    store = MemoryEventStore()
    store.append("ORD-0001", SAMPLES[:1], expected_version=0)
    with pytest.raises(ConcurrencyError):
        store.append("ORD-0001", SAMPLES[1:2], expected_version=0)


def test_events_go_to_their_own_stream() -> None:
    with pytest.raises(ValueError):
        MemoryEventStore().append("ORD-0002", SAMPLES[:1], expected_version=0)
