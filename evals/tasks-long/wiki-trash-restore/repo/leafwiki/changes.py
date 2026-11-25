"""The recent-changes log: one entry per thing that happened to a page."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from .clock import parse
from .models import CHANGE_KINDS, Change
from .storage import Store


class ChangeLog:
    def __init__(self, store: Store) -> None:
        self.store = store

    def record(self, change: Change) -> Change:
        if change.kind not in CHANGE_KINDS:
            raise ValueError(f"unknown change kind {change.kind!r}")
        self.store.append_change(change)
        return change

    def recent(
        self,
        limit: int | None = 50,
        kinds: Iterable[str] | None = None,
        page_id: str | None = None,
        author: str | None = None,
    ) -> list[Change]:
        """Newest first."""
        wanted = set(kinds) if kinds else None
        out = [
            change
            for change in reversed(self.store.read_changes())
            if (wanted is None or change.kind in wanted)
            and (page_id is None or change.page_id == page_id)
            and (author is None or change.author == author)
        ]
        return out if limit is None else out[:limit]

    def trim(self, now: datetime, keep_days: int) -> int:
        """Drop entries older than ``keep_days``; returns how many went."""
        cutoff = now - timedelta(days=keep_days)
        changes = self.store.read_changes()
        kept = [c for c in changes if parse(c.at) >= cutoff]
        if len(kept) != len(changes):
            self.store.write_changes(kept)
        return len(changes) - len(kept)

    def by_day(self, limit: int | None = 50) -> list[tuple[str, list[Change]]]:
        """Recent changes grouped by date (newest day first), for the export's page."""
        groups: list[tuple[str, list[Change]]] = []
        for change in self.recent(limit):
            day = change.at[:10]
            if groups and groups[-1][0] == day:
                groups[-1][1].append(change)
            else:
                groups.append((day, [change]))
        return groups


def describe(change: Change) -> str:
    """One line for the CLI and the export: "2026-03-01 09:00 edit Kettle by ana — fix"."""
    when = change.at.replace("T", " ")[:16]
    who = f" by {change.author}" if change.author else ""
    why = f" — {change.summary}" if change.summary else ""
    return f"{when} {change.kind} {change.title}{who}{why}"
