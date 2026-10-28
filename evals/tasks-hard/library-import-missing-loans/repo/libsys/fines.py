"""Overdue fines."""

from datetime import date
from decimal import Decimal

from libsys.models import Branch, Loan

ZERO = Decimal("0.00")


def fine_for(loan: Loan, branch: Branch, as_of: date) -> Decimal:
    """What a loan owes on `as_of`: fine_per_day for each day overdue, up to the cap.

    A loan due on the 1st is overdue on the 2nd, so on the 2nd it owes one day.
    """
    # TODO: the desks don't charge for days the branch is closed; we have no opening
    # hours yet, so we charge every day and let the desk waive the difference.
    days = loan.days_overdue(as_of)
    if days <= 0:
        return ZERO
    return min(branch.fine_per_day * days, branch.fine_cap).quantize(Decimal("0.01"))


def format_money(amount: Decimal) -> str:
    return f"${amount:.2f}"
