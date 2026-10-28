"""`python -m inventory.cli stock.csv` prints the stock report for a CSV export."""

import sys
from pathlib import Path

from inventory import load_items, render_report


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m inventory.cli STOCK.csv", file=sys.stderr)
        return 2
    warehouse = load_items(Path(argv[0]).read_text(encoding="utf-8"))
    print(render_report(warehouse))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
