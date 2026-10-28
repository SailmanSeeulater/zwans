"""The records stockroom keeps. Each one turns into a plain dict for the database file
with to_record() and back with from_record()."""

from dataclasses import asdict, dataclass
from typing import Any

MOVEMENT_KINDS = ("receive", "ship", "adjust")


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    unit_cost_cents: int
    reorder_level: int = 0  # 0 means: never warn about this one
    unit: str = "pcs"

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Product":
        return cls(
            sku=record["sku"],
            name=record["name"],
            unit_cost_cents=record["unit_cost_cents"],
            reorder_level=record.get("reorder_level", 0),
            unit=record.get("unit", "pcs"),
        )


@dataclass(frozen=True)
class Movement:
    """A change in stock: positive qty comes in, negative goes out."""

    id: str
    sku: str
    kind: str  # one of MOVEMENT_KINDS
    qty: int
    ref: str
    at: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Movement":
        return cls(
            id=record["id"],
            sku=record["sku"],
            kind=record["kind"],
            qty=record["qty"],
            ref=record.get("ref", ""),
            at=record["at"],
        )


@dataclass(frozen=True)
class Alert:
    """Raised once when a product's stock drops to its reorder level or below."""

    sku: str
    on_hand: int
    reorder_level: int
    at: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Alert":
        return cls(record["sku"], record["on_hand"], record["reorder_level"], record["at"])
