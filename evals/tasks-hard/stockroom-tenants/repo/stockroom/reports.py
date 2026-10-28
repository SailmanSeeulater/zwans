"""Reports. They only read, so they go straight to the repositories instead of through the
Inventory service, and read each table once rather than once per product."""

import csv
import io

from .repos import AlertRepo, MovementRepo, ProductRepo
from .storage import Database
from .validation import format_cents


def valuation_report(db: Database) -> str:
    """Stock value per product (on hand x unit cost), most valuable first, with a total."""
    totals = MovementRepo(db).on_hand_by_sku()
    rows = []
    for product in ProductRepo(db).all():
        qty = totals.get(product.sku, 0)
        rows.append((product.unit_cost_cents * qty, product.sku, qty, product))
    rows.sort(key=lambda row: (-row[0], row[1]))
    lines = [f"{'sku':<16} {'on hand':>8} {'unit cost':>10} {'value':>12}"]
    for value, sku, qty, product in rows:
        lines.append(
            f"{sku:<16} {qty:>8} {format_cents(product.unit_cost_cents):>10} {format_cents(value):>12}"
        )
    lines.append(f"{'total':<16} {'':>8} {'':>10} {format_cents(sum(row[0] for row in rows)):>12}")
    return "\n".join(lines) + "\n"


def low_stock_report(db: Database) -> str:
    """Products at or below their reorder level, with how many to order to get back above."""
    totals = MovementRepo(db).on_hand_by_sku()
    lines = []
    for product in ProductRepo(db).all():
        qty = totals.get(product.sku, 0)
        if product.reorder_level > 0 and qty <= product.reorder_level:
            short = product.reorder_level - qty + 1
            lines.append(
                f"{product.sku}  {product.name}  on hand {qty}  reorder level {product.reorder_level}  order {short}"
            )
    return "\n".join(lines) + "\n" if lines else "nothing is low\n"


def movements_csv(db: Database, sku: str | None = None) -> str:
    """Stock movements as CSV, oldest first: id, sku, kind, qty, ref, at."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", "sku", "kind", "qty", "ref", "at"])
    for movement in MovementRepo(db).all():
        if sku is None or movement.sku == sku:
            writer.writerow(
                [movement.id, movement.sku, movement.kind, movement.qty, movement.ref, movement.at]
            )
    return out.getvalue()


def alerts_report(db: Database) -> str:
    lines = [
        f"{alert.at}  {alert.sku}  on hand {alert.on_hand} (reorder level {alert.reorder_level})"
        for alert in AlertRepo(db).all()
    ]
    return "\n".join(lines) + "\n" if lines else "no alerts\n"
