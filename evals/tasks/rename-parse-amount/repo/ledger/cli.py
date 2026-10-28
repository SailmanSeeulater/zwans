"""`python -m ledger.cli 12.50 3.25 ...` prints the sum of the amounts."""

import sys

import ledger.money


def main(argv: list[str]) -> int:
    try:
        total = sum(ledger.money.parse_amt(arg) for arg in argv)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(ledger.money.format_cents(total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
