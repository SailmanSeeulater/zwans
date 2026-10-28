"""Supplier invoices waiting for approval."""

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ledgerdesk.clock import parse_instant
from ledgerdesk.money import Money

STATUSES = ("draft", "pending", "approved", "paid", "void")


class InvoiceError(Exception):
    pass


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    owner: str  # the employee who manages our relationship with this vendor


@dataclass(frozen=True)
class Approval:
    username: str
    at: datetime
    step: int


@dataclass
class Invoice:
    id: str
    vendor: Vendor
    total: Money
    invoice_date: date  # the date printed on the invoice
    received: date
    submitted_by: str
    cost_center: str
    status: str = "pending"
    approvals: list[Approval] = field(default_factory=list)

    @property
    def next_step(self) -> int:
        return len(self.approvals) + 1

    def approved_by(self, username: str) -> bool:
        return any(approval.username == username for approval in self.approvals)


class InvoiceBook:
    def __init__(self, invoices: list[Invoice]):
        self._invoices = {invoice.id: invoice for invoice in invoices}

    def get(self, invoice_id: str) -> Invoice:
        try:
            return self._invoices[invoice_id.strip().upper()]
        except KeyError:
            raise InvoiceError(f"no such invoice {invoice_id!r}") from None

    def all(self) -> list[Invoice]:
        return [self._invoices[key] for key in sorted(self._invoices)]

    def pending(self) -> list[Invoice]:
        return [invoice for invoice in self.all() if invoice.status == "pending"]


def load_invoices(path: Path) -> InvoiceBook:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    vendors = {v["id"]: Vendor(v["id"], v["name"], v["owner"]) for v in raw["vendors"]}
    invoices = []
    for entry in raw["invoices"]:
        if entry["status"] not in STATUSES:
            raise InvoiceError(f"{entry['id']}: unknown status {entry['status']!r}")
        approvals = [
            Approval(a["user"], parse_instant(a["at"]), step)
            for step, a in enumerate(entry.get("approvals", []), start=1)
        ]
        invoices.append(
            Invoice(
                id=entry["id"],
                vendor=vendors[entry["vendor"]],
                total=Money(Decimal(entry["total"]), entry["currency"]),
                invoice_date=date.fromisoformat(entry["invoice_date"]),
                received=date.fromisoformat(entry["received"]),
                submitted_by=entry["submitted_by"],
                cost_center=entry["cost_center"],
                status=entry["status"],
                approvals=approvals,
            )
        )
    return InvoiceBook(invoices)
