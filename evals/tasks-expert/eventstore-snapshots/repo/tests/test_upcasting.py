import pytest

import stockflow  # noqa: F401  (registers the domain)
from stockflow import InMemoryEventStore, Repository
from stockflow.domain import Order, StockItem
from stockflow.errors import EventShapeError, UpcastError
from stockflow.events import NewEvent, current_version, decode
from stockflow.legacy import Scan, import_scans, parse_scans
from stockflow.upcasting import upcast


def test_every_old_shape_comes_up_to_date() -> None:
    assert upcast("StockReceived", 1, {"count": 4}) == {"quantity": 4, "lot": "unlabelled"}
    assert upcast("StockAdjusted", 1, {"amount": -3}) == {"delta": -3, "reason": "unspecified"}
    assert upcast("StockAdjusted", 2, {"delta": 2}) == {"delta": 2, "reason": "unspecified"}
    assert upcast("LineAdded", 1, {"sku": "a", "qty": 2, "price": 0.29}) == {
        "sku": "a",
        "quantity": 2,
        "unit_price_cents": 29,
    }
    assert upcast("OrderPlaced", 1, {"customer": "x"}) == {"customer": "x"}


def test_upcasting_leaves_the_input_alone() -> None:
    data = {"count": 4}
    upcast("StockReceived", 1, data)
    assert data == {"count": 4}


def test_unknown_or_future_versions_are_errors() -> None:
    with pytest.raises(UpcastError):
        upcast("StockReceived", current_version("StockReceived") + 1, {})


def test_old_shapes_dont_decode_without_upcasting() -> None:
    with pytest.raises(EventShapeError):
        decode("StockReceived", {"count": 4})


def test_old_events_in_a_stream_load_fine() -> None:
    store = InMemoryEventStore()
    store.append("item-a", [NewEvent("ItemRegistered", 1, {"sku": "a", "name": "A", "reorder_level": 0})], 0)
    store.append("item-a", [NewEvent("StockReceived", 1, {"count": 10})], 1)
    store.append("item-a", [NewEvent("StockAdjusted", 2, {"delta": -2})], 2)
    store.append("order-1", [NewEvent("OrderPlaced", 1, {"customer": "c"})], 0)
    store.append("order-1", [NewEvent("LineAdded", 1, {"sku": "a", "qty": 3, "price": 1.5})], 1)
    repository = Repository(store)

    item = repository.load(StockItem, "a")
    order = repository.load(Order, "1")

    assert item.on_hand == 8 and item.lots == {"unlabelled": 10}
    assert order.total_cents == 450
    assert repository.stats.events_replayed == 5


def test_scanner_receipts_are_stored_as_the_scanners_write_them() -> None:
    store = InMemoryEventStore()
    store.append("item-a", [NewEvent("ItemRegistered", 1, {"sku": "a", "name": "A", "reorder_level": 0})], 0)
    scans = parse_scans("a,in,12\n# comment\na,fix,-2\nunknown,in,5\n")

    assert scans[0] == Scan("a", "in", 12)
    assert import_scans(store, scans) == 2
    assert [(e.type, e.schema, e.data) for e in store.read("item-a", after=1)] == [
        ("StockReceived", 1, {"count": 12}),
        ("StockAdjusted", 1, {"amount": -2}),
    ]
    assert Repository(store).load(StockItem, "a").on_hand == 10
