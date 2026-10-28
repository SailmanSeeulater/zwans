"""Bulk import of products from CSV.

    sku,name,unit_cost,reorder_level,opening_stock
    MUG-01,Blue mug,4.25,10,40

unit_cost is in currency units ("4.25"); reorder_level and opening_stock may be empty
(meaning 0). The import is all or nothing: one bad row and nothing is imported.
"""

import csv
import io
from dataclasses import dataclass

from .errors import InvalidInput
from .inventory import Inventory
from .validation import parse_cents

COLUMNS = ("sku", "name", "unit_cost", "reorder_level", "opening_stock")


@dataclass
class ImportResult:
    added: list[str]


def _int(text: str | None, what: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    if not text.isdigit():
        raise InvalidInput(f"{what} must be a whole number, not {text!r}")
    return int(text)


def import_products(inventory: Inventory, text: str) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not {"sku", "name", "unit_cost"} <= set(reader.fieldnames):
        raise InvalidInput(
            f"the CSV needs at least the columns sku, name and unit_cost (allowed: {', '.join(COLUMNS)})"
        )
    added: list[str] = []
    with inventory.db.transaction():
        for line, row in enumerate(reader, start=2):
            try:
                product = inventory.add_product(
                    row["sku"],
                    row["name"],
                    parse_cents(row["unit_cost"]),
                    _int(row.get("reorder_level"), "reorder_level"),
                )
                opening = _int(row.get("opening_stock"), "opening_stock")
                if opening:
                    inventory.receive(product.sku, opening, ref="opening stock")
            except InvalidInput as exc:
                raise InvalidInput(f"line {line}: {exc}") from exc
            added.append(product.sku)
    return ImportResult(added)
