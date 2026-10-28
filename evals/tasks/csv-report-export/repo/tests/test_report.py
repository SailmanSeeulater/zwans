import json
from decimal import Decimal
from pathlib import Path

import pytest

from sales.__main__ import main
from sales.orders import Order, load_orders
from sales.report import Row, build_report, to_text

ORDERS = [
    Order("North", "Kettle", 3, Decimal("25.00")),
    Order("North", "Toaster", 1, Decimal("40.00")),
    Order("South", "Kettle", 2, Decimal("25.00")),
    Order("North", "Kettle", 1, Decimal("24.50")),
]


def test_build_report_groups_and_sorts() -> None:
    report = build_report(ORDERS)

    assert report.rows == [
        Row("North", "Kettle", 4, Decimal("99.50")),
        Row("North", "Toaster", 1, Decimal("40.00")),
        Row("South", "Kettle", 2, Decimal("50.00")),
    ]
    assert report.total_units == 7
    assert report.total_revenue == Decimal("189.50")


def test_to_text() -> None:
    text = to_text(build_report(ORDERS))

    lines = text.splitlines()
    assert lines[0].split() == ["REGION", "PRODUCT", "UNITS", "REVENUE"]
    assert lines[1].split() == ["North", "Kettle", "4", "99.50"]
    assert lines[-1].split() == ["TOTAL", "7", "189.50"]


def test_cli_prints_the_text_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "orders.json"
    path.write_text(
        json.dumps([{"region": "East", "product": "Lamp", "units": 2, "unit_price": 1500}]),
        encoding="utf-8",
    )
    assert load_orders(path)[0].unit_price == Decimal(1500)

    assert main([str(path)]) == 0

    assert capsys.readouterr().out.splitlines()[1].split() == ["East", "Lamp", "2", "3,000.00"]
