import csv
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

from sales.__main__ import main
from sales.orders import Order
from sales.report import Report, build_report, to_csv

ORDERS = [
    Order("North", "Kettle", 3, Decimal("25.00")),
    Order("North", "Toaster", 1, Decimal("40.00")),
    Order("South", "Kettle", 2, Decimal("25.00")),
    Order("North", "Kettle", 1, Decimal("24.50")),
]


def test_plain_csv() -> None:
    assert to_csv(build_report(ORDERS)) == (
        "region,product,units,revenue\n"
        "North,Kettle,4,99.50\n"
        "North,Toaster,1,40.00\n"
        "South,Kettle,2,50.00\n"
        "TOTAL,,7,189.50\n"
    )


def test_no_thousands_separator() -> None:
    report = build_report([Order("East", "Sofa", 3, Decimal("1234.5"))])

    assert to_csv(report).splitlines()[1] == "East,Sofa,3,3703.50"


def test_empty_report() -> None:
    assert to_csv(Report([])) == "region,product,units,revenue\nTOTAL,,0,0.00\n"


def test_awkward_names_survive_a_round_trip() -> None:
    names = [
        ("West, coast", 'Mug "Large"'),
        ("West, coast", "Plate\nset of 4"),
        ("Zone ;1", "  padded  "),
        ("Ørsted", "Crème brûlée torch"),
    ]
    orders = [Order(region, product, 1, Decimal("2")) for region, product in names]
    report = build_report(orders)

    text = to_csv(report)
    rows = list(csv.reader(io.StringIO(text, newline="")))

    assert rows[0] == ["region", "product", "units", "revenue"]
    assert [(row[0], row[1]) for row in rows[1:-1]] == [
        (row.region, row.product) for row in report.rows
    ]
    assert rows[-1] == ["TOTAL", "", "4", "8.00"]
    assert "\r" not in text


def test_quotes_are_doubled() -> None:
    report = build_report([Order("A", 'Say "hi"', 1, Decimal("1"))])

    assert to_csv(report).splitlines()[1] == 'A,"Say ""hi""",1,1.00'


def test_cli_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "orders.json"
    path.write_text(
        json.dumps(
            [
                {"region": "East", "product": "Lamp, desk", "units": 2, "unit_price": 1500},
                {"region": "East", "product": "Bulb", "units": 10, "unit_price": "0.99"},
            ]
        ),
        encoding="utf-8",
    )

    assert main([str(path), "--format", "csv"]) == 0

    assert capsys.readouterr().out == (
        "region,product,units,revenue\n"
        'East,"Lamp, desk",2,3000.00\n'
        "East,Bulb,10,9.90\n"
        "TOTAL,,12,3009.90\n"
    )


def test_cli_text_is_still_the_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "orders.json"
    path.write_text(
        json.dumps([{"region": "East", "product": "Lamp", "units": 2, "unit_price": 1500}]),
        encoding="utf-8",
    )

    main([str(path)])
    default = capsys.readouterr().out
    main([str(path), "--format", "text"])

    assert capsys.readouterr().out == default
    assert default.splitlines()[0].split() == ["REGION", "PRODUCT", "UNITS", "REVENUE"]


def test_cli_rejects_other_formats(tmp_path: Path) -> None:
    path = tmp_path / "orders.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit):
        main([str(path), "--format", "xml"])
