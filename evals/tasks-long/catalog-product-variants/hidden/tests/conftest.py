import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shopdesk import Shop  # noqa: E402
from shopdesk.cli.main import main  # noqa: E402

DATA = Path(__file__).parent / "data"

MUG_EAN = "5012345678900"
KETTLE_EAN = "5012345678917"
TEA_EAN = "5012345678924"


class Clock:
    """Ticks one minute per call, from 2026-03-02T09:00:00Z."""

    def __init__(self, start_day: str = "2026-03-02") -> None:
        self.day = start_day
        self.minutes = 0

    def __call__(self) -> str:
        at = f"{self.day}T{9 + self.minutes // 60:02d}:{self.minutes % 60:02d}:00Z"
        self.minutes += 1
        return at


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def shop(clock: Clock) -> Shop:
    return Shop(clock=clock)


def stock_up(shop: Shop) -> Shop:
    """A small shop: two warehouses, a few kitchen things and some tea."""
    shop.add_category("home", "Home")
    shop.add_category("kitchen", "Kitchen", "home")
    shop.add_category("pantry", "Pantry")
    shop.add_warehouse("MAIN", "Main warehouse", 0)
    shop.add_warehouse("WEST", "West store", 1)
    shop.add_product(
        "MUG-01", "Blue mug", 1250, category="kitchen", brand="Potter", barcode=MUG_EAN,
        reorder_level=5, cost=400, description="A blue stoneware mug.",
    )
    shop.add_product(
        "KET-02", "Red kettle", 3999, category="kitchen", brand="Boilco", barcode=KETTLE_EAN,
        reorder_level=2, cost=2100,
    )
    shop.add_product(
        "TEA-07", "Green tea, 100 g", 450, category="pantry", brand="Leaf & Co",
        barcode=TEA_EAN, tax_class="reduced", cost=150,
    )
    shop.receive("MUG-01", "MAIN", 20, "PO-1")
    shop.receive("MUG-01", "WEST", 5, "PO-1")
    shop.receive("KET-02", "MAIN", 6, "PO-1")
    shop.receive("TEA-07", "WEST", 40, "PO-2")
    return shop


@pytest.fixture
def stocked(shop: Shop) -> Shop:
    return stock_up(shop)


TEE_EAN = {"TEE-S-RED": "8712345000011", "TEE-M-RED": "8712345000028", "TEE-M-BLUE": "8712345000035"}


def dress_up(shop: Shop) -> Shop:
    """stock_up, plus a tee in three variants. The tee's own SKU, TEE-01, is not one of
    its variants. TEE-M-RED has a reorder level of its own; TEE-M-BLUE a price of its own.

        TEE-S-RED   size S, colour red    15.00   MAIN 10
        TEE-M-RED   size M, colour red    15.00   MAIN 8, WEST 4   reorder at 5
        TEE-M-BLUE  size M, colour blue   17.00   WEST 6
    """
    stock_up(shop)
    shop.add_category("clothing", "Clothing")
    shop.add_product(
        "TEE-01", "Logo tee", 1500, category="clothing", brand="Shopdesk", cost=600,
        reorder_level=3, variants=[
            {"sku": "TEE-S-RED", "options": {"size": "S", "colour": "red"},
             "barcode": TEE_EAN["TEE-S-RED"]},
            {"sku": "TEE-M-RED", "options": {"size": "M", "colour": "red"},
             "barcode": TEE_EAN["TEE-M-RED"], "reorder_level": 5},
            {"sku": "TEE-M-BLUE", "options": {"size": "M", "colour": "blue"}, "price": 1700,
             "barcode": TEE_EAN["TEE-M-BLUE"]},
        ],
    )
    shop.receive("TEE-S-RED", "MAIN", 10)
    shop.receive("TEE-M-RED", "MAIN", 8)
    shop.receive("TEE-M-RED", "WEST", 4)
    shop.receive("TEE-M-BLUE", "WEST", 6)
    return shop


@pytest.fixture
def dressed(shop: Shop) -> Shop:
    return dress_up(shop)


def sell(shop: Shop, customer: str, *lines: tuple[str, int], **cart_options) -> str:
    cart = shop.new_cart(cart_options.pop("price_list", None))
    for sku, qty in lines:
        shop.cart_add(cart, sku, qty)
    if "code" in cart_options:
        shop.cart_code(cart, cart_options["code"])
    return shop.checkout(cart, customer).number


@pytest.fixture
def old_file(tmp_path: Path) -> Callable[[str], Path]:
    """A copy of one of the data files written by earlier releases."""

    def copy(name: str) -> Path:
        target = tmp_path / name
        shutil.copy(DATA / name, target)
        return target

    return copy


@pytest.fixture
def cli(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> Callable:
    """cli("product", "add", ...) -> (exit code, stdout, stderr), on a data file of its own."""
    path = tmp_path / "shop.json"
    monkeypatch.setenv("SHOPDESK_NOW", "2026-03-02T09:00:00Z")
    monkeypatch.chdir(tmp_path)

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--db", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    return run
