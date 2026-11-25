"""The change history behind `undo`, and the log `billfold history` prints.

Every change to transactions (adding, editing, deleting, transfers, splits, imports,
recurring runs) records what the affected transactions looked like before and after.
Undo puts the "before" back. The history is kept in the data file, newest last, and
trimmed to the last `history_limit` entries.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from .errors import NothingToUndo
from .models import Split, Transaction
from .money import to_amount


@dataclass
class HistoryEntry:
    seq: int
    at: str
    op: str
    summary: str
    before: list[dict] = field(default_factory=list)
    after: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "at": self.at,
            "op": self.op,
            "summary": self.summary,
            "before": self.before,
            "after": self.after,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HistoryEntry:
        return cls(
            seq=int(data["seq"]),
            at=data.get("at", ""),
            op=data.get("op", "?"),
            summary=data.get("summary", ""),
            before=list(data.get("before", [])),
            after=list(data.get("after", [])),
        )


def snapshot(txn: Transaction) -> dict:
    """A plain, JSON-friendly copy of a transaction."""
    return {
        "id": txn.id,
        "account": txn.account,
        "date": txn.date.isoformat(),
        "amount": format(txn.amount, "f"),
        "payee": txn.payee,
        "memo": txn.memo,
        "category": txn.category,
        "splits": [
            {"category": s.category, "amount": format(s.amount, "f"), "memo": s.memo}
            for s in txn.splits
        ],
        "tags": list(txn.tags),
        "transfer_id": txn.transfer_id,
        "recurring_id": txn.recurring_id,
        "cleared": txn.cleared,
        "import_ref": txn.import_ref,
    }


def revive(data: dict, currency: str) -> Transaction:
    return Transaction(
        id=data["id"],
        account=data["account"],
        date=date.fromisoformat(data["date"]),
        amount=to_amount(data["amount"], currency),
        payee=data.get("payee", ""),
        memo=data.get("memo", ""),
        category=data.get("category"),
        splits=[
            Split(s.get("category"), to_amount(s["amount"], currency), s.get("memo", ""))
            for s in data.get("splits", [])
        ],
        tags=list(data.get("tags", [])),
        transfer_id=data.get("transfer_id"),
        recurring_id=data.get("recurring_id"),
        cleared=bool(data.get("cleared", False)),
        import_ref=data.get("import_ref"),
    )


class History:
    def __init__(self, limit: int = 50, entries: Iterable[HistoryEntry] = ()) -> None:
        self.limit = limit
        self._entries: list[HistoryEntry] = list(entries)

    def record(
        self,
        op: str,
        summary: str,
        before: Iterable[Transaction],
        after: Iterable[Transaction],
        at: str,
    ) -> HistoryEntry:
        seq = self._entries[-1].seq + 1 if self._entries else 1
        entry = HistoryEntry(
            seq, at, op, summary, [snapshot(t) for t in before], [snapshot(t) for t in after]
        )
        self._entries.append(entry)
        if self.limit and len(self._entries) > self.limit:
            del self._entries[: len(self._entries) - self.limit]
        return entry

    def pop(self) -> HistoryEntry:
        if not self._entries:
            raise NothingToUndo("nothing to undo")
        return self._entries.pop()

    def last(self, count: int = 10) -> list[HistoryEntry]:
        return self._entries[-count:]

    def __len__(self) -> int:
        return len(self._entries)

    def to_list(self) -> list[dict]:
        return [entry.to_dict() for entry in self._entries]

    @classmethod
    def from_list(cls, items: Iterable[dict], limit: int = 50) -> History:
        return cls(limit, [HistoryEntry.from_dict(item) for item in items])
