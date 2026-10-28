"""The nightly import of the desks' circulation events."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from libsys import circulation
from libsys.circulation import CirculationError
from libsys.clock import TimestampError, parse_utc
from libsys.config import BranchDirectory
from libsys.models import EVENT_KINDS, LoanEvent
from libsys.store import LibraryStore
from libsys.util import group_by, plural


class RowError(Exception):
    pass


@dataclass
class ImportResult:
    applied: Counter[str] = field(default_factory=Counter)  # events per branch code
    rejected: list[tuple[int, str]] = field(default_factory=list)  # (line, reason)

    @property
    def total(self) -> int:
        return sum(self.applied.values())

    def describe(self) -> str:
        parts = [f"{code} {count}" for code, count in sorted(self.applied.items())]
        text = f"applied {plural(self.total, 'event')}"
        if parts:
            text += f" ({', '.join(parts)})"
        if self.rejected:
            text += f", rejected {len(self.rejected)}"
        return text


def parse_row(row: dict[str, str], branches: BranchDirectory, line: int) -> LoanEvent:
    kind = row.get("event", "").strip().lower()
    if kind not in EVENT_KINDS:
        raise RowError(f"unknown event {row.get('event')!r}")
    branch = branches.resolve(row.get("branch", ""))
    try:
        number = int(row.get("loan_no", ""))
    except ValueError:
        raise RowError(f"loan_no must be a number, not {row.get('loan_no')!r}") from None
    member = row.get("member", "").strip().upper()
    if kind == "issue" and not member:
        raise RowError("an issue needs a member")
    try:
        at = parse_utc(row.get("at", ""))
    except TimestampError as exc:
        raise RowError(str(exc)) from None
    return LoanEvent(
        kind=kind,
        branch=branch,
        number=number,
        member=member,
        barcode=row.get("barcode", "").strip(),
        title=row.get("title", ""),
        at=at,
        line=line,
    )


def apply_event(store: LibraryStore, event: LoanEvent) -> None:
    if event.kind == "issue":
        circulation.issue(
            store, event.branch, event.number, event.member, event.barcode, event.title, event.at
        )
    elif event.kind == "renew":
        circulation.renew(store, event.branch, event.number, event.at)
    else:
        circulation.give_back(store, event.branch, event.number, event.at)


def import_events(
    store: LibraryStore, rows: Iterable[dict[str, str]], branches: BranchDirectory
) -> ImportResult:
    """Apply an export's rows to the store. Bad rows are rejected, not fatal.

    Rows are parsed first, then applied branch by branch, each branch's events in the
    order they appear in the file.
    """
    result = ImportResult()
    events: list[LoanEvent] = []
    for line, row in enumerate(rows, start=2):  # line 1 is the header
        try:
            events.append(parse_row(row, branches, line))
        except RowError as exc:
            result.rejected.append((line, str(exc)))

    for code, batch in group_by(events, key=lambda event: event.branch.code).items():
        for event in batch:
            try:
                apply_event(store, event)
            except CirculationError as exc:
                result.rejected.append((event.line, str(exc)))
            else:
                result.applied[code] += 1
    result.rejected.sort()
    return result
