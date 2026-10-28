"""A JSON snapshot of the catalogue and stock levels, for the web shop to pick up.

    {"generated_at": "...", "products": [{"sku": ..., "name": ..., "unit": ..., "on_hand": 3}, ...]}

Costs are internal and never leave stockroom, so they are not in the snapshot.
"""

import json

from .inventory import Inventory


def snapshot(inventory: Inventory) -> dict:
    return {
        "generated_at": inventory.clock(),
        "products": [
            {"sku": product.sku, "name": product.name, "unit": product.unit, "on_hand": qty}
            for product, qty in inventory.levels()
        ],
    }


def snapshot_json(inventory: Inventory) -> str:
    return json.dumps(snapshot(inventory), indent=2, sort_keys=True) + "\n"
