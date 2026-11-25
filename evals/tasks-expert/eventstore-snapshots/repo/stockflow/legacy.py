"""Receipts and recounts from the warehouse scanners.

The scanner gateway predates schema versions and still records receipts as StockReceived
v1 ({"count": n}) and recounts as StockAdjusted v1 ({"amount": n}). We append them to the
store exactly as the scanners record them, so the scan log stays verbatim; the upcasters
bring them up to date whenever they are read. They don't go through the StockItem
commands: a scan is a fact about the shelf, not a request.
"""

import csv
import io
from dataclasses import dataclass

from stockflow.domain.inventory import StockItem
from stockflow.errors import StockflowError
from stockflow.events import NewEvent
from stockflow.store.base import EventStore

RECEIPT = "in"
RECOUNT = "fix"


class ScanError(StockflowError):
    pass


@dataclass(frozen=True)
class Scan:
    sku: str
    kind: str  # "in" (units received) or "fix" (a recount: units found or missing)
    amount: int


def parse_scans(text: str) -> list[Scan]:
    """CSV lines `sku,kind,amount`, as the scanner gateway exports them."""
    scans = []
    for number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not row or row[0].startswith("#"):
            continue
        if len(row) != 3:
            raise ScanError(f"line {number}: expected sku,kind,amount")
        sku, kind, amount = (cell.strip() for cell in row)
        if kind not in (RECEIPT, RECOUNT):
            raise ScanError(f"line {number}: unknown scan kind {kind!r}")
        try:
            value = int(amount)
        except ValueError:
            raise ScanError(f"line {number}: {amount!r} is not a number") from None
        if kind == RECEIPT and value <= 0:
            raise ScanError(f"line {number}: a receipt must be positive")
        scans.append(Scan(sku, kind, value))
    return scans


def scan_event(scan: Scan) -> NewEvent:
    if scan.kind == RECEIPT:
        return NewEvent("StockReceived", 1, {"count": scan.amount})
    return NewEvent("StockAdjusted", 1, {"amount": scan.amount})


def import_scans(store: EventStore, scans: list[Scan]) -> int:
    """Append each scan to its item's stream. Scans for items that aren't registered are
    skipped. Returns how many were imported."""
    imported = 0
    for scan in scans:
        stream = StockItem.stream_for(scan.sku)
        version = store.version(stream)
        if version == 0:
            continue
        store.append(stream, [scan_event(scan)], expected_version=version)
        imported += 1
    return imported
