"""Upcasters for the domain's older event schemas.

StockReceived v1 (the warehouse scanners still write it): {"count": n}, no lot.
StockAdjusted v1: {"amount": n}; v2 renamed it to "delta"; v3 added "reason".
LineAdded v1: {"sku", "qty", "price"} with the price in dollars as a float.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from stockflow.upcasting import upcaster

UNLABELLED_LOT = "unlabelled"


@upcaster("StockReceived", from_version=1)
def received_v1(data: dict[str, Any]) -> dict[str, Any]:
    return {"quantity": int(data["count"]), "lot": UNLABELLED_LOT}


@upcaster("StockAdjusted", from_version=1)
def adjusted_v1(data: dict[str, Any]) -> dict[str, Any]:
    return {"delta": int(data["amount"])}


@upcaster("StockAdjusted", from_version=2)
def adjusted_v2(data: dict[str, Any]) -> dict[str, Any]:
    return {"delta": data["delta"], "reason": "unspecified"}


@upcaster("LineAdded", from_version=1)
def line_added_v1(data: dict[str, Any]) -> dict[str, Any]:
    cents = (Decimal(str(data["price"])) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return {"sku": data["sku"], "quantity": int(data["qty"]), "unit_price_cents": int(cents)}
