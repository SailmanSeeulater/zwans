"""Totals per region and product."""

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sales.orders import Order


@dataclass(frozen=True)
class Row:
    region: str
    product: str
    units: int
    revenue: Decimal


@dataclass(frozen=True)
class Report:
    rows: list[Row]

    @property
    def total_units(self) -> int:
        return sum(row.units for row in self.rows)

    @property
    def total_revenue(self) -> Decimal:
        return sum((row.revenue for row in self.rows), Decimal(0))


def build_report(orders: list[Order]) -> Report:
    """One row per (region, product), sorted by region, then by revenue, highest first."""
    units: dict[tuple[str, str], int] = defaultdict(int)
    revenue: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for order in orders:
        key = (order.region, order.product)
        units[key] += order.units
        revenue[key] += order.units * order.unit_price
    rows = [Row(*key, units[key], revenue[key]) for key in units]
    rows.sort(key=lambda row: (row.region, -row.revenue, row.product))
    return Report(rows)


def _money(amount: Decimal) -> str:
    return f"{amount:,.2f}"


def to_text(report: Report) -> str:
    lines = [f"{'REGION':<12} {'PRODUCT':<24} {'UNITS':>7} {'REVENUE':>12}"]
    for row in report.rows:
        lines.append(
            f"{row.region:<12} {row.product:<24} {row.units:>7} {_money(row.revenue):>12}"
        )
    lines.append(
        f"{'TOTAL':<12} {'':<24} {report.total_units:>7} {_money(report.total_revenue):>12}"
    )
    return "\n".join(lines) + "\n"


def to_csv(report: Report) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["region", "product", "units", "revenue"])
    for row in report.rows:
        writer.writerow([row.region, row.product, row.units, f"{row.revenue:.2f}"])
    writer.writerow(["TOTAL", "", report.total_units, f"{report.total_revenue:.2f}"])
    return out.getvalue()
