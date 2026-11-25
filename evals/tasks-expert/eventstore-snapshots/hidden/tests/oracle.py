"""What a full replay of a stream gives, worked out from the raw stored events with no help
from stockflow: its own copy of the upcasting rules and of what each event does, producing
the same plain data as as_dict()."""

from decimal import ROUND_HALF_UP, Decimal

KNOWN_TYPES = {
    "ItemRegistered",
    "StockReceived",
    "StockReserved",
    "ReservationReleased",
    "StockShipped",
    "StockAdjusted",
    "OrderPlaced",
    "LineAdded",
    "LineRemoved",
    "OrderConfirmed",
    "OrderCancelled",
    "OrderShipped",
}


def current(event) -> tuple[str, dict]:
    kind, schema, data = event.type, event.schema, dict(event.data)
    if kind == "StockReceived" and schema == 1:
        data = {"quantity": data["count"], "lot": "unlabelled"}
    if kind == "StockAdjusted" and schema == 1:
        data = {"delta": data["amount"], "reason": "unspecified"}
    if kind == "StockAdjusted" and schema == 2:
        data = {"delta": data["delta"], "reason": "unspecified"}
    if kind == "LineAdded" and schema == 1:
        cents = (Decimal(str(data["price"])) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        data = {"sku": data["sku"], "quantity": data["qty"], "unit_price_cents": int(cents)}
    return kind, data


def item(sku: str, events: list) -> tuple[dict, int]:
    name, reorder, on_hand, shipped = None, 0, 0, 0
    reservations: dict[str, int] = {}
    lots: dict[str, int] = {}
    for event in events:
        kind, data = current(event)
        if kind == "ItemRegistered":
            name, reorder = data["name"], data["reorder_level"]
        elif kind == "StockReceived":
            on_hand += data["quantity"]
            lots[data["lot"]] = lots.get(data["lot"], 0) + data["quantity"]
        elif kind == "StockReserved":
            reservations[data["order_id"]] = data["quantity"]
        elif kind == "ReservationReleased":
            reservations.pop(data["order_id"], None)
        elif kind == "StockShipped":
            quantity = reservations.pop(data["order_id"], 0)
            on_hand -= quantity
            shipped += quantity
        elif kind == "StockAdjusted":
            on_hand += data["delta"]
        else:
            raise AssertionError(f"{kind} in an item stream")
    reserved = sum(reservations.values())
    state = {
        "sku": sku,
        "name": name,
        "reorder_level": reorder,
        "on_hand": on_hand,
        "reserved": reserved,
        "available": on_hand - reserved,
        "reservations": dict(sorted(reservations.items())),
        "lots": dict(sorted(lots.items())),
        "shipped": shipped,
    }
    return state, len(events)


def order(order_id: str, events: list) -> tuple[dict, int]:
    customer, status, reason = None, None, None
    lines: dict[str, dict[str, int]] = {}
    for event in events:
        kind, data = current(event)
        if kind == "OrderPlaced":
            customer, status = data["customer"], "draft"
        elif kind == "LineAdded":
            line = lines.setdefault(data["sku"], {"quantity": 0, "unit_price_cents": 0})
            line["quantity"] += data["quantity"]
            line["unit_price_cents"] = data["unit_price_cents"]
        elif kind == "LineRemoved":
            lines.pop(data["sku"], None)
        elif kind == "OrderConfirmed":
            status = "confirmed"
        elif kind == "OrderCancelled":
            status, reason = "cancelled", data["reason"]
        elif kind == "OrderShipped":
            status = "shipped"
        else:
            raise AssertionError(f"{kind} in an order stream")
    state = {
        "id": order_id,
        "customer": customer,
        "status": status,
        "lines": {sku: dict(line) for sku, line in sorted(lines.items())},
        "total_cents": sum(l["quantity"] * l["unit_price_cents"] for l in lines.values()),
        "cancel_reason": reason,
    }
    return state, len(events)


def replay(stream: str, events: list) -> tuple[dict, int]:
    """(as_dict, version) of the aggregate behind a stream, by full replay."""
    kind, _, id = stream.partition("-")
    return (item if kind == "item" else order)(id, events)


class SnapshotRule:
    """Where each stream's latest snapshot must be, per the README: after a save, if the
    version is `every` or more past the latest snapshot (or 0), a snapshot at the new
    version. Only saves move it."""

    def __init__(self, every: int) -> None:
        self.every = every
        self.at: dict[str, int] = {}

    def saved(self, stream: str, version: int) -> None:
        if self.every > 0 and version - self.at.get(stream, 0) >= self.every:
            self.at[stream] = version

    def replayed_by_load(self, stream: str, version: int) -> int:
        return version - self.at.get(stream, 0)
