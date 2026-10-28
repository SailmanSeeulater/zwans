"""Which loans are overdue, and the morning report the desks print."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from libsys.clock import format_day
from libsys.config import BranchDirectory
from libsys.fines import fine_for, format_money
from libsys.models import Loan
from libsys.reports import table
from libsys.store import LibraryStore
from libsys.util import group_by, plural


@dataclass(frozen=True)
class OverdueLoan:
    loan: Loan
    days: int
    fine: Decimal


def overdue_loans(store: LibraryStore, branches: BranchDirectory, as_of: date) -> list[OverdueLoan]:
    """Every open loan due before `as_of`, by branch, then oldest due date first."""
    result = []
    for loan in store.open_loans():
        if loan.is_overdue(as_of):
            branch = branches.get(loan.branch)
            result.append(
                OverdueLoan(loan, loan.days_overdue(as_of), fine_for(loan, branch, as_of))
            )
    result.sort(
        key=lambda item: (item.loan.branch, item.loan.due, item.loan.member, item.loan.number)
    )
    return result


def overdue_report(store: LibraryStore, branches: BranchDirectory, as_of: date) -> str:
    items = overdue_loans(store, branches, as_of)
    lines = [f"Overdue loans as of {format_day(as_of)}", ""]
    if not items:
        return "\n".join(lines + ["Nothing is overdue."]) + "\n"
    for code, group in group_by(items, key=lambda item: item.loan.branch).items():
        branch = branches.get(code)
        total = sum((item.fine for item in group), Decimal("0.00"))
        lines.append(f"{branch.name} ({plural(len(group), 'loan')}, fines {format_money(total)})")
        rows = [
            [
                f"{code}-{item.loan.number}",
                item.loan.member,
                item.loan.title,
                format_day(item.loan.due),
                str(item.days),
                format_money(item.fine),
            ]
            for item in group
        ]
        lines += table(["loan", "member", "title", "due", "days", "fine"], rows, right={4, 5})
        lines.append("")
    return "\n".join(lines)
