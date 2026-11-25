"""CLI: search, the feeds and the reports."""

import argparse
from pathlib import Path
from typing import Any

from shopdesk.cli.output import Context, command, group, key_values, money_arg
from shopdesk.clock import parse_day
from shopdesk.money import format_money
from shopdesk.reports import tables
from shopdesk.reports.sales import category_report, daily_report, sales_report, totals
from shopdesk.reports.stock import stock_report, valuation


def register(commands: Any) -> None:
    p = command(commands, "search", search, help="search products")
    p.add_argument("text", nargs="?", default="")
    p.add_argument("--category")
    p.add_argument("--brand")
    p.add_argument("--in-stock", action="store_true")
    p.add_argument("--min", type=money_arg, dest="price_min")
    p.add_argument("--max", type=money_arg, dest="price_max")
    p.add_argument("--option", action="append", metavar="NAME=VALUE", default=[])
    p.add_argument("--sort", default="relevance")
    p.add_argument("--facets", action="store_true", help="print facet counts too")

    p = command(commands, "feed", feed, help="write the product feed")
    p.add_argument("format", choices=("xml", "csv"))
    p.add_argument("--out", type=Path, help="file to write (default: print)")

    reports = group(commands, "report", "reports")
    for name, handler in (
        ("sales", report_sales),
        ("categories", report_categories),
        ("daily", report_daily),
    ):
        p = command(reports, name, handler, help=f"{name} report")
        p.add_argument("--from", dest="start", type=parse_day)
        p.add_argument("--to", dest="end", type=parse_day)
        p.add_argument("--csv", action="store_true")
        if name == "sales":
            p.add_argument("--by-variant", action="store_true", help="one row per variant")
    p = command(reports, "stock", report_stock, help="stock per warehouse")
    p.add_argument("--low", action="store_true", help="only items at or below reorder level")
    p.add_argument("--csv", action="store_true")
    p = command(reports, "valuation", report_valuation, help="stock at cost")
    p.add_argument("--csv", action="store_true")


def search(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.shop.search(
        args.text,
        category=args.category,
        brand=args.brand,
        in_stock=True if args.in_stock else None,
        price_min=args.price_min,
        price_max=args.price_max,
        options=key_values(args.option) or None,
        sort=args.sort,
    )
    for sku in result.hits:
        product = ctx.shop.product(sku)
        ctx.say(f"{product.sku:<16} {ctx.money(product.price):>12}  {product.name}")
    ctx.say(f"{result.total} found")
    if args.facets:
        for facet, counts in result.facets.items():
            shown = ", ".join(f"{k}: {v}" for k, v in counts.items())
            ctx.say(f"{facet}: {shown}")
    return 0


def feed(ctx: Context, args: argparse.Namespace) -> int:
    text = ctx.shop.feed_xml() if args.format == "xml" else ctx.shop.feed_csv()
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        ctx.say(f"Wrote {len(ctx.shop.feed_items())} items to {args.out}")
    else:
        ctx.out.write(text)
    return 0


def _emit(ctx: Context, as_csv: bool, headers: list[str], rows: list[list], numeric: set[int]) -> None:
    if as_csv:
        ctx.out.write(tables.render_csv(headers, rows))
    else:
        ctx.out.write(tables.render_table(headers, rows, numeric=numeric))


def report_sales(ctx: Context, args: argparse.Namespace) -> int:
    rows = sales_report(ctx.shop, args.start, args.end, by_variant=args.by_variant)
    body = [[r.sku, r.name, r.units, format_money(r.revenue), r.orders] for r in rows]
    if not args.csv:
        units, revenue = totals(rows)
        body.append(["total", "", units, format_money(revenue), ""])
    _emit(ctx, args.csv, ["sku", "name", "units", "revenue", "orders"], body, {2, 3, 4})
    return 0


def report_categories(ctx: Context, args: argparse.Namespace) -> int:
    rows = category_report(ctx.shop, args.start, args.end)
    body = [[r.category, r.name, r.units, format_money(r.revenue)] for r in rows]
    _emit(ctx, args.csv, ["category", "name", "units", "revenue"], body, {2, 3})
    return 0


def report_daily(ctx: Context, args: argparse.Namespace) -> int:
    rows = daily_report(ctx.shop, args.start, args.end)
    body = [[r.day, r.orders, r.units, format_money(r.revenue)] for r in rows]
    _emit(ctx, args.csv, ["day", "orders", "units", "revenue"], body, {1, 2, 3})
    return 0


def report_stock(ctx: Context, args: argparse.Namespace) -> int:
    rows = stock_report(ctx.shop, low_only=args.low)
    codes = ctx.shop.warehouses.codes()
    body = [
        [r.sku, r.name, *(r.warehouses.get(c, 0) for c in codes), r.total, "LOW" if r.low else ""]
        for r in rows
    ]
    headers = ["sku", "name", *codes, "total", ""]
    _emit(ctx, args.csv, headers, body, set(range(2, 3 + len(codes))))
    return 0


def report_valuation(ctx: Context, args: argparse.Namespace) -> int:
    rows, total = valuation(ctx.shop)
    body = [[r.sku, r.name, r.units, format_money(r.cost), format_money(r.value)] for r in rows]
    if not args.csv:
        body.append(["total", "", "", "", format_money(total)])
    _emit(ctx, args.csv, ["sku", "name", "units", "cost", "value"], body, {2, 3, 4})
    return 0
