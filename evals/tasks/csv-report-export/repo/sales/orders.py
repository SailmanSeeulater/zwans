"""Orders as they come out of the shop's export: a JSON list of objects."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass(frozen=True)
class Order:
    region: str
    product: str
    units: int
    unit_price: Decimal


def load_orders(path: Path) -> list[Order]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Order(
            region=item["region"],
            product=item["product"],
            units=int(item["units"]),
            unit_price=Decimal(str(item["unit_price"])),
        )
        for item in raw
    ]
