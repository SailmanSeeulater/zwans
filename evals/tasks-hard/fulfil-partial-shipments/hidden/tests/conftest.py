import pytest
from fulfil import Shop


class Clock:
    """A clock the test moves by hand: clock.day = "2026-03-02"."""

    def __init__(self) -> None:
        self.day = "2026-03-01"
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"{self.day}T09:{self.ticks // 60:02d}:{self.ticks % 60:02d}Z"


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def shop(clock: Clock) -> Shop:
    """A shop with three products in stock."""
    shop = Shop(clock=clock)
    shop.add_product("MUG-01", "Blue mug", 950)
    shop.add_product("TEA-07", "Green tea", 1100)
    shop.add_product("CUP-03", "Paper cup", 10)
    shop.receive("MUG-01", 10)
    shop.receive("TEA-07", 10)
    shop.receive("CUP-03", 100)
    return shop
