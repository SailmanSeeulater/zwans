"""Holds: members queue for a title at a branch; returned copies go to the first in line."""

from datetime import datetime

from libsys.models import Hold
from libsys.store import LibraryStore
from libsys.util import group_by


class HoldError(Exception):
    pass


MAX_HOLDS_PER_MEMBER = 5


def _same_title(a: str, b: str) -> bool:
    return " ".join(a.casefold().split()) == " ".join(b.casefold().split())


def waiting(store: LibraryStore, branch: str, title: str) -> list[Hold]:
    """Unfulfilled holds for a title at a branch, first placed first."""
    holds = [
        hold
        for hold in store.holds
        if hold.branch == branch and hold.fulfilled_by is None and _same_title(hold.title, title)
    ]
    return sorted(holds, key=lambda hold: (hold.placed_at, hold.member))


def place_hold(store: LibraryStore, branch: str, title: str, member: str, at: datetime) -> Hold:
    if any(hold.member == member for hold in waiting(store, branch, title)):
        raise HoldError(f"{member} is already waiting for {title!r}")
    open_holds = [h for h in store.holds if h.member == member and h.fulfilled_by is None]
    if len(open_holds) >= MAX_HOLDS_PER_MEMBER:
        raise HoldError(f"{member} already has {MAX_HOLDS_PER_MEMBER} holds")
    hold = Hold(branch, title.strip(), member, at)
    store.holds.append(hold)
    return hold


def cancel_hold(store: LibraryStore, branch: str, title: str, member: str) -> None:
    for hold in waiting(store, branch, title):
        if hold.member == member:
            store.holds.remove(hold)
            return
    raise HoldError(f"{member} has no hold on {title!r}")


def copy_returned(store: LibraryStore, branch: str, title: str, barcode: str) -> Hold | None:
    """A copy came back: give it to the first member in line, if anyone is waiting."""
    queue = waiting(store, branch, title)
    if not queue:
        return None
    first = queue[0]
    first.fulfilled_by = barcode
    return first


def queue_lengths(store: LibraryStore) -> dict[tuple[str, str], int]:
    """How many members wait for each (branch, title)."""
    pending = sorted(
        (hold for hold in store.holds if hold.fulfilled_by is None),
        key=lambda hold: (hold.branch, hold.title.casefold()),
    )
    groups = group_by(pending, key=lambda hold: (hold.branch, hold.title.casefold()))
    return {(branch, group[0].title): len(group) for (branch, _), group in groups.items()}
