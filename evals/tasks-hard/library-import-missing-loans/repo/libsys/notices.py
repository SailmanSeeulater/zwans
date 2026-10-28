"""Overdue notices: one per member, listing every loan they have overdue."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from libsys.clock import format_day
from libsys.config import BranchDirectory
from libsys.fines import format_money
from libsys.overdue import OverdueLoan, overdue_loans
from libsys.reports import indent
from libsys.store import LibraryStore
from libsys.util import group_by


@dataclass(frozen=True)
class Notice:
    member: str
    name: str
    email: str
    items: tuple[OverdueLoan, ...]

    @property
    def total(self) -> Decimal:
        return sum((item.fine for item in self.items), Decimal("0.00"))


def build_notices(store: LibraryStore, branches: BranchDirectory, as_of: date) -> list[Notice]:
    """Members with something overdue, in member order. Within a notice, the loan that
    has been overdue longest comes first."""
    items = sorted(
        overdue_loans(store, branches, as_of), key=lambda item: (item.loan.due, item.loan.key)
    )
    notices = []
    for member_id, overdue in group_by(items, key=lambda item: item.loan.member).items():
        member = store.member(member_id)
        notices.append(Notice(member_id, member.name, member.email, tuple(overdue)))
    return sorted(notices, key=lambda notice: notice.member)


def render_notice(notice: Notice, branches: BranchDirectory, as_of: date) -> str:
    greeting = f"Dear {notice.name}," if notice.name else f"Dear member {notice.member},"
    count = len(notice.items)
    lines = [
        greeting,
        "",
        f"As of {format_day(as_of)} you have {'an overdue item' if count == 1 else f'{count} overdue items'}:",
        "",
    ]
    body = []
    for item in notice.items:
        branch = branches.get(item.loan.branch)
        body.append(
            f"- {item.loan.title} (due {format_day(item.loan.due)} at {branch.name}, "
            f"fine so far {format_money(item.fine)})"
        )
    lines += indent(body, 0)
    lines += [
        "",
        f"Total fines: {format_money(notice.total)}",
        "Please return or renew them as soon as you can.",
        "",
    ]
    return "\n".join(lines)
