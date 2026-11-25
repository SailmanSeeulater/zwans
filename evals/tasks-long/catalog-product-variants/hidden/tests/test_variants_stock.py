from conftest import sell


def test_stock_is_kept_per_variant(dressed) -> None:
    assert dressed.stock("TEE-M-RED") == 12
    assert dressed.stock("TEE-M-RED", "WEST") == 4
    assert dressed.ledger.by_warehouse("TEE-M-BLUE") == {"MAIN": 0, "WEST": 6}
    dressed.transfer("TEE-M-BLUE", "WEST", "MAIN", 2)
    dressed.count("TEE-S-RED", "MAIN", 9)
    assert dressed.ledger.by_warehouse("TEE-M-BLUE") == {"MAIN": 2, "WEST": 4}
    assert dressed.stock("TEE-S-RED") == 9
    assert {m.sku for m in dressed.ledger.history("TEE-S-RED")} == {"TEE-S-RED"}
    assert dressed.stock("TEE-M-RED") == 12


def test_each_variant_alerts_against_its_own_reorder_level(dressed) -> None:
    sell(dressed, "Ann", ("TEE-M-RED", 7))  # 12 -> 5, its own level is 5
    [alert] = dressed.alerts()
    assert (alert.sku, alert.stock, alert.reorder_level) == ("TEE-M-RED", 5, 5)
    sell(dressed, "Bob", ("TEE-S-RED", 6))  # 10 -> 4, the product's level is 3
    assert [a.sku for a in dressed.alerts()] == ["TEE-M-RED"]
    sell(dressed, "Cy", ("TEE-S-RED", 1))
    assert [(a.sku, a.reorder_level) for a in dressed.alerts()] == [
        ("TEE-M-RED", 5),
        ("TEE-S-RED", 3),
    ]


def test_variants_of_one_product_have_separate_alerts(dressed) -> None:
    sell(dressed, "Ann", ("TEE-M-BLUE", 3), ("TEE-S-RED", 7))
    assert sorted(a.sku for a in dressed.alerts()) == ["TEE-M-BLUE", "TEE-S-RED"]
    dressed.receive("TEE-M-BLUE", "MAIN", 10)
    assert [a.sku for a in dressed.alerts()] == ["TEE-S-RED"]


def test_changing_the_products_reorder_level_rechecks_its_variants(dressed) -> None:
    dressed.update_product("TEE-01", reorder_level=10)
    # S-RED has 10 and M-BLUE 6, both at or below 10; M-RED keeps its own level of 5.
    assert sorted(a.sku for a in dressed.alerts()) == ["TEE-M-BLUE", "TEE-S-RED"]
    assert {a.reorder_level for a in dressed.alerts()} == {10}


def test_changing_a_variants_reorder_level_rechecks_it(dressed) -> None:
    dressed.update_variant("TEE-M-BLUE", reorder_level=6)
    [alert] = dressed.alerts()
    assert (alert.sku, alert.reorder_level) == ("TEE-M-BLUE", 6)
    dressed.update_variant("TEE-M-BLUE", reorder_level=2)
    assert dressed.alerts() == []


def test_the_low_stock_notification_names_the_variant(dressed) -> None:
    sell(dressed, "Ann", ("TEE-M-RED", 9))
    [note] = [n for n in dressed.outbox() if n.topic == "stock.low"]
    assert note.payload["sku"] == "TEE-M-RED"
    assert note.payload["name"] == "Logo tee (colour: red, size: M)"
    assert note.payload["stock"] == 3
    assert note.payload["reorder_level"] == 5
    assert note.payload["warehouses"] == {"MAIN": 0, "WEST": 3}


def test_single_variant_products_alert_as_before(dressed) -> None:
    sell(dressed, "Ann", ("KET-02", 4))
    [alert] = dressed.alerts()
    assert (alert.sku, alert.reorder_level) == ("KET-02", 2)
    [note] = [n for n in dressed.outbox() if n.topic == "stock.low"]
    assert note.payload["name"] == "Red kettle"
