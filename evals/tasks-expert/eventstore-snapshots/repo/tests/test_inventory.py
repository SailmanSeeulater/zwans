import pytest

from stockflow import ConcurrencyError, DomainError, InMemoryEventStore, Inventory, NotFound, Repository
from stockflow.domain import CANCELLED, CONFIRMED, SHIPPED, Order, StockItem


@pytest.fixture
def inventory() -> Inventory:
    service = Inventory(Repository(InMemoryEventStore()))
    service.register_item("bolt", "Bolt", 10)
    service.register_item("nut", "Nut")
    service.receive("bolt", 100, "L1")
    service.receive("nut", 40, "L1")
    return service


def test_items(inventory: Inventory) -> None:
    inventory.receive("bolt", 20, "L2")
    inventory.adjust("bolt", -5, "damaged")

    assert inventory.item("bolt").as_dict() == {
        "sku": "bolt",
        "name": "Bolt",
        "reorder_level": 10,
        "on_hand": 115,
        "reserved": 0,
        "available": 115,
        "reservations": {},
        "lots": {"L1": 100, "L2": 20},
        "shipped": 0,
    }


def test_item_rules(inventory: Inventory) -> None:
    with pytest.raises(DomainError):
        inventory.register_item("bolt", "Again")
    with pytest.raises(DomainError):
        inventory.receive("bolt", 0, "L1")
    with pytest.raises(DomainError):
        inventory.receive("washer", 1, "L1")
    with pytest.raises(DomainError):
        inventory.adjust("bolt", -101, "lost")


def test_an_order_from_draft_to_shipped(inventory: Inventory) -> None:
    inventory.place_order("o1", "Acme", [("bolt", 30, 12)])
    inventory.add_line("o1", "nut", 10, 5)
    inventory.add_line("o1", "bolt", 5, 11)
    inventory.confirm_order("o1")

    bolt = inventory.item("bolt")
    assert (bolt.on_hand, bolt.reserved, bolt.available) == (100, 35, 65)
    assert inventory.order("o1").status == CONFIRMED

    inventory.ship_order("o1")

    order = inventory.order("o1").as_dict()
    assert order["status"] == SHIPPED
    assert order["lines"] == {
        "bolt": {"quantity": 35, "unit_price_cents": 11},
        "nut": {"quantity": 10, "unit_price_cents": 5},
    }
    assert order["total_cents"] == 35 * 11 + 50
    assert inventory.item("bolt").as_dict()["shipped"] == 35
    assert inventory.item("nut").on_hand == 30


def test_confirming_without_enough_stock_changes_nothing(inventory: Inventory) -> None:
    inventory.place_order("o1", "Acme", [("bolt", 30, 1), ("nut", 41, 1)])

    with pytest.raises(DomainError):
        inventory.confirm_order("o1")

    assert inventory.item("bolt").reserved == 0
    assert inventory.order("o1").status == "draft"


def test_cancelling_a_confirmed_order_releases_its_stock(inventory: Inventory) -> None:
    inventory.place_order("o1", "Acme", [("bolt", 30, 1)])
    inventory.confirm_order("o1")

    inventory.cancel_order("o1", "changed their mind")

    assert inventory.item("bolt").available == 100
    assert inventory.order("o1").as_dict()["status"] == CANCELLED
    with pytest.raises(DomainError):
        inventory.ship_order("o1")


def test_stock_reserved_for_one_order_isnt_there_for_another(inventory: Inventory) -> None:
    inventory.place_order("o1", "Acme", [("nut", 30, 1)])
    inventory.place_order("o2", "Bobs", [("nut", 30, 1)])
    inventory.confirm_order("o1")

    with pytest.raises(DomainError):
        inventory.confirm_order("o2")
    with pytest.raises(DomainError):
        inventory.adjust("nut", -11, "recount")


def test_two_writers_on_one_item(inventory: Inventory) -> None:
    repository = inventory.repository
    mine = repository.load(StockItem, "bolt")
    theirs = repository.load(StockItem, "bolt")
    mine.receive(5, "L3")
    theirs.adjust(-1, "damaged")
    repository.save(mine)

    with pytest.raises(ConcurrencyError):
        repository.save(theirs)
    assert repository.load(StockItem, "bolt").on_hand == 105


def test_loading_what_isnt_there(inventory: Inventory) -> None:
    with pytest.raises(NotFound):
        inventory.repository.load(Order, "nope")


def test_load_stats_count_events_replayed() -> None:
    repository = Repository(InMemoryEventStore())
    service = Inventory(repository)
    service.register_item("bolt", "Bolt")
    for _ in range(9):
        service.receive("bolt", 1, "L")
    before = repository.stats.events_replayed

    item = repository.load(StockItem, "bolt")

    assert item.version == 10
    assert repository.stats.events_replayed - before == 10
