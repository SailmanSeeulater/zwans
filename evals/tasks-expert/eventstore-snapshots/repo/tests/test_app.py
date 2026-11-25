import json

import pytest

from stockflow import App, Settings
from stockflow.cli import main, parse_price
from stockflow.errors import SettingsError


def test_settings_from_a_file(tmp_path) -> None:
    (tmp_path / "stockflow.toml").write_text(
        "[store]\nfsync = false\n[inventory]\nlow_stock_threshold = 12\n", encoding="utf-8"
    )

    settings = Settings.load(tmp_path)

    assert settings.fsync is False and settings.low_stock_threshold == 12
    assert Settings.load(tmp_path / "nowhere") == Settings()


@pytest.mark.parametrize(
    "text",
    ["[stor]\nfsync = true", "[store]\nfsink = true", "[store]\nfsync = 1", "[inventory]\nlow_stock_threshold = -1"],
)
def test_bad_settings(tmp_path, text: str) -> None:
    (tmp_path / "stockflow.toml").write_text(text, encoding="utf-8")
    with pytest.raises(SettingsError):
        Settings.load(tmp_path)


def test_reports() -> None:
    app = App.open()
    app.inventory.register_item("bolt", "Bolt", 50)
    app.inventory.register_item("nut", "Nut")
    app.inventory.receive("bolt", 100, "L1")
    app.inventory.receive("nut", 8, "L1")
    app.inventory.place_order("o1", "Acme", [("bolt", 60, 3)])
    app.inventory.confirm_order("o1")
    app.inventory.place_order("o2", "Bobs", [("nut", 1, 100)])

    assert app.projector.result("stock_levels")["bolt"] == {
        "name": "Bolt",
        "on_hand": 100,
        "reserved": 60,
        "available": 40,
        "reorder_level": 50,
    }
    assert app.projector.result("low_stock") == ["bolt"]
    assert app.projector.result("open_orders") == {
        "o1": {"customer": "Acme", "status": "confirmed", "total_cents": 180},
        "o2": {"customer": "Bobs", "status": "draft", "total_cents": 100},
    }
    app.inventory.ship_order("o1")
    assert list(app.projector.result("open_orders")) == ["o2"]


def test_parse_price() -> None:
    assert parse_price("12") == 1200
    assert parse_price("0.5") == 50
    assert parse_price("3.07") == 307


def test_the_command_line(tmp_path, capsys) -> None:
    data = ["--data", str(tmp_path)]
    (tmp_path / "stockflow.toml").write_text("[store]\nfsync = false\n", encoding="utf-8")
    assert main(data + ["item", "register", "bolt", "Bolt"]) == 0
    assert main(data + ["item", "receive", "bolt", "40", "--lot", "A"]) == 0
    (tmp_path / "scans.csv").write_text("bolt,in,5\n", encoding="utf-8")
    assert main(data + ["scans", "import", str(tmp_path / "scans.csv")]) == 0
    assert main(data + ["order", "place", "o1", "Acme"]) == 0
    assert main(data + ["order", "add", "o1", "bolt", "10", "1.25"]) == 0
    assert main(data + ["order", "confirm", "o1"]) == 0
    assert main(data + ["order", "confirm", "o1"]) == 1
    capsys.readouterr()

    assert main(data + ["--json", "item", "show", "bolt"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert (shown["on_hand"], shown["reserved"]) == (45, 10)
    assert shown["lots"] == {"A": 40, "unlabelled": 5}
