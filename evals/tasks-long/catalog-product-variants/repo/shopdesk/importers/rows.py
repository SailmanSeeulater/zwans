"""Reading supplier price files.

Suppliers send CSV with a header row, separated by commas or semicolons. Column names
vary, so common aliases are mapped to ours; unknown columns are kept in `extras`. A row
that can't be understood becomes an error for that line, not for the file.
"""

import csv
import io
from dataclasses import dataclass, field

from shopdesk.codes import normalize_barcode, normalize_sku
from shopdesk.errors import InvalidInput, SupplierFileError
from shopdesk.money import parse_money

ALIASES = {
    "sku": "sku",
    "code": "sku",
    "item": "sku",
    "article": "sku",
    "name": "name",
    "title": "name",
    "description": "name",
    "price": "price",
    "rrp": "price",
    "retail": "price",
    "cost": "cost",
    "trade": "cost",
    "net": "cost",
    "barcode": "barcode",
    "ean": "barcode",
    "gtin": "barcode",
    "upc": "barcode",
    "category": "category",
    "brand": "brand",
    "make": "brand",
    "ref": "supplier_ref",
    "supplier_ref": "supplier_ref",
}


@dataclass
class SupplierRow:
    line: int
    sku: str
    name: str | None = None
    price: int | None = None
    cost: int | None = None
    barcode: str | None = None
    category: str | None = None
    brand: str | None = None
    supplier_ref: str | None = None
    extras: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedFile:
    rows: list[SupplierRow]
    errors: list[tuple[int, str]]
    columns: list[str]


def _delimiter(header: str) -> str:
    return ";" if header.count(";") > header.count(",") else ","


def _canonical(column: str) -> str:
    key = column.strip().lower().replace(" ", "_")
    return ALIASES.get(key, key)


def parse_supplier_file(text: str) -> ParsedFile:
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise SupplierFileError("The supplier file is empty.")
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(lines[0]))
    header = [_canonical(c) for c in next(reader)]
    if "sku" not in header:
        raise SupplierFileError("The supplier file has no SKU column.")
    duplicated = {c for c in header if header.count(c) > 1}
    if duplicated:
        raise SupplierFileError(f"Columns appear twice: {', '.join(sorted(duplicated))}.")
    rows: list[SupplierRow] = []
    errors: list[tuple[int, str]] = []
    for number, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            continue
        record = dict(zip(header, (c.strip() for c in cells), strict=False))
        try:
            rows.append(_row(number, record))
        except InvalidInput as exc:
            errors.append((number, str(exc)))
    return ParsedFile(rows, errors, header)


def _row(number: int, record: dict[str, str]) -> SupplierRow:
    known = set(SupplierRow.__dataclass_fields__) - {"line", "extras"}
    row = SupplierRow(line=number, sku=normalize_sku(record.get("sku", "")))
    for key, value in record.items():
        if key == "sku" or value == "":
            continue
        if key in ("price", "cost"):
            setattr(row, key, parse_money(value))
        elif key == "barcode":
            row.barcode = normalize_barcode(value)
        elif key in known:
            setattr(row, key, value)
        else:
            row.extras[key] = value
    return row
