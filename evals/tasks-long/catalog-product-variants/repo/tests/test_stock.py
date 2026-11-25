import pytest
from conftest import sell

from shopdesk.errors import InvalidInput, OutOfStock, UnknownWarehouse


def test_stock_is_the_sum_of_moves_per_warehouse(stocked) -> None:
    assert stocked.stock("MUG-01") == 25
    assert stocked.stock("MUG-01", "MAIN") == 20
    assert stocked.ledger.by_warehouse("MUG-01") == {"MAIN": 20, "WEST": 5}
    assert stocked.stock("TEA-07", "MAIN") == 0


def test_stock_never_goes_below_zero(stocked) -> None:
    with pytest.raises(OutOfStock):
        stocked.adjust("MUG-01", "WEST", -6)
    stocked.adjust("MUG-01", "WEST", -5, "broken")
    assert stocked.stock("MUG-01", "WEST") == 0


def test_transfer_moves_stock_between_warehouses(stocked) -> None:
    ref = stocked.transfer("MUG-01", "MAIN", "WEST", 7)
    assert stocked.ledger.by_warehouse("MUG-01") == {"MAIN": 13, "WEST": 12}
    assert [m.qty for m in stocked.ledger.moves_for(ref)] == [-7, 7]
    with pytest.raises(OutOfStock):
        stocked.transfer("KET-02", "WEST", "MAIN", 1)
    with pytest.raises(InvalidInput):
        stocked.transfer("KET-02", "MAIN", "MAIN", 1)
    with pytest.raises(UnknownWarehouse):
        stocked.transfer("KET-02", "MAIN", "EAST", 1)


def test_a_count_sets_the_stock_to_what_was_counted(stocked) -> None:
    move = stocked.count("MUG-01", "MAIN", 18)
    assert (move.qty, move.reason) == (-2, "count")
    assert stocked.stock("MUG-01", "MAIN") == 18
    assert stocked.count("MUG-01", "MAIN", 18) is None


def test_an_alert_is_raised_once_when_stock_falls_to_the_reorder_level(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 3))
    assert stocked.alerts() == []
    sell(stocked, "Bob", ("KET-02", 1))
    [alert] = stocked.alerts()
    assert (alert.sku, alert.stock, alert.reorder_level) == ("KET-02", 2, 2)
    sell(stocked, "Cy", ("KET-02", 1))
    assert len(stocked.alerts()) == 1


def test_an_alert_clears_when_stock_recovers_and_can_come_back(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 4))
    stocked.receive("KET-02", "MAIN", 10)
    assert stocked.alerts() == []
    assert len(stocked.alerts(open_only=False)) == 1
    sell(stocked, "Bob", ("KET-02", 10))
    assert len(stocked.alerts()) == 1
    assert len(stocked.alerts(open_only=False)) == 2


def test_products_without_a_reorder_level_never_alert(stocked) -> None:
    sell(stocked, "Ann", ("TEA-07", 40))
    assert stocked.alerts() == []


def test_raising_the_reorder_level_can_raise_an_alert(stocked) -> None:
    stocked.update_product("MUG-01", reorder_level=30)
    [alert] = stocked.alerts()
    assert alert.sku == "MUG-01"


def test_a_low_stock_alert_queues_a_notification(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 4))
    notes = [n for n in stocked.outbox() if n.topic == "stock.low"]
    assert len(notes) == 1
    assert notes[0].payload == {
        "sku": "KET-02",
        "name": "Red kettle",
        "stock": 2,
        "reorder_level": 2,
        "warehouses": {"MAIN": 2, "WEST": 0},
        "supplier": None,
    }


def test_flushing_the_outbox_marks_messages_sent(stocked) -> None:
    sell(stocked, "Ann", ("KET-02", 4))
    sent = []
    assert stocked.notifier.flush(sent.append) == 2
    assert [n.topic for n in sent] == ["stock.low", "order.placed"]
    assert stocked.outbox() == []
