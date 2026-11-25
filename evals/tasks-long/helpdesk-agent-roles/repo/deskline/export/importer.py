"""Importing customers from a CSV file (name, email, phone, address, organization).

Rows whose email matches an existing customer update that customer; other rows create
new customers. Rows without a name are skipped.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from ..context import Context
from ..errors import DesklineError
from ..services import customers

FIELDS = ("name", "email", "phone", "address", "organization")


@dataclass
class ImportResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[tuple[int, str]] = field(default_factory=list)


def import_customers(ctx: Context, text: str) -> ImportResult:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "name" not in [f.strip().lower() for f in reader.fieldnames]:
        raise DesklineError("the CSV needs at least a 'name' column")
    result = ImportResult()
    with ctx.store.transaction():
        for line, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            if not row.get("name"):
                result.skipped.append((line, "no name"))
                continue
            values = {k: row.get(k, "") for k in FIELDS}
            existing = ctx.store.customer_by_email(values["email"]) if values["email"] else None
            try:
                if existing is not None:
                    customers.update(ctx, existing.id, **{k: v for k, v in values.items() if v})
                    result.updated.append(existing.id)
                else:
                    name = values.pop("name")
                    created = customers.create(ctx, name, **values)
                    result.created.append(created.id)
            except DesklineError as exc:
                result.skipped.append((line, exc.message))
    return result
