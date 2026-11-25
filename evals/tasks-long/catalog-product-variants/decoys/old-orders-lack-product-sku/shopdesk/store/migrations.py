"""Upgrading data files written by older releases.

Each step takes the raw JSON document of one version and returns the next version's.
`upgrade` runs every step a document needs, so any older file can be opened; saving it
then writes the current version.

Version history:
  1  shopdesk 0.x: prices as decimal strings, one stock figure per product, no
     warehouses, no discounts or invoices.
  2  prices in cents, warehouses and the stock-move ledger, discounts, price lists,
     invoices, the outbox.
  3  product variants: every product has a list of variants (SKU, options, price,
     barcode, reorder level); the barcode moved from the product to its variants. Order
     and invoice lines carry the product's SKU next to the variant's.
"""

import copy
from collections.abc import Callable
from typing import Any

from shopdesk.errors import StoreError
from shopdesk.money import parse_money

FORMAT_VERSION = 3

Raw = dict[str, Any]


def _v1_to_v2(raw: Raw) -> Raw:
    out = copy.deepcopy(raw)
    for product in out.get("products", []):
        product["price"] = parse_money(product.get("price", "0"))
        product["cost"] = parse_money(product.get("cost", "0"))
    saved_at = raw.get("saved_at", "1970-01-01T00:00:00Z")
    out["warehouses"] = [{"code": "MAIN", "name": "Main warehouse", "priority": 0}]
    moves = []
    for sku, qty in sorted(raw.get("stock", {}).items()):
        if qty:
            moves.append(
                {
                    "id": len(moves) + 1,
                    "at": saved_at,
                    "sku": sku,
                    "warehouse": "MAIN",
                    "qty": qty,
                    "reason": "opening",
                    "ref": "upgrade from version 1",
                }
            )
    out["moves"] = moves
    out.pop("stock", None)
    counters = out.setdefault("counters", {})
    counters["move"] = len(moves)
    for order in out.get("orders", []):
        for line in order.get("lines", []):
            line["unit_price"] = parse_money(line.pop("price", "0"))
            line.setdefault("discount", 0)
            line["allocations"] = [{"warehouse": "MAIN", "qty": line["qty"]}]
    out["version"] = 2
    return out


def _v2_to_v3(raw: Raw) -> Raw:
    out = copy.deepcopy(raw)
    for product in out.get("products", []):
        barcode = product.pop("barcode", None)
        product["variants"] = [
            {
                "sku": product["sku"],
                "options": {},
                "price": None,
                "barcode": barcode,
                "reorder_level": None,
            }
        ]
    out["version"] = 3
    return out


STEPS: dict[int, Callable[[Raw], Raw]] = {1: _v1_to_v2, 2: _v2_to_v3}


def upgrade(raw: Raw) -> Raw:
    if raw.get("format") != "shopdesk":
        raise StoreError("This is not a shopdesk data file.")
    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise StoreError(f"Unknown data file version {version!r}.")
    if version > FORMAT_VERSION:
        raise StoreError(
            f"The data file is version {version}; this shopdesk reads up to {FORMAT_VERSION}. "
            "Upgrade shopdesk."
        )
    while version < FORMAT_VERSION:
        raw = STEPS[version](raw)
        version = raw["version"]
    return raw
