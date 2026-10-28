import argparse
import sys
from pathlib import Path

from sales.orders import load_orders
from sales.report import build_report, to_csv, to_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sales", description="Summarise an order export.")
    parser.add_argument("orders", type=Path, help="the JSON order export")
    parser.add_argument("--format", choices=["text", "csv"], default="text")
    args = parser.parse_args(argv)

    report = build_report(load_orders(args.orders))
    render = to_csv if args.format == "csv" else to_text
    sys.stdout.write(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
