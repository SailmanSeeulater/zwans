"""Reading bank exports: one `date,description,amount` row per line."""

import csv
import io

from ledger import money


def read_rows(text: str) -> list[tuple[str, str, int]]:
    rows = []
    for record in csv.reader(io.StringIO(text)):
        if not record or record[0] == "date":
            continue
        date, description, amount = record
        rows.append((date, description.strip(), money.parse_amount(amount)))
    return rows


def balance(text: str, opening: str = "0") -> int:
    return money.parse_amount(opening) + sum(amount for _, _, amount in read_rows(text))
