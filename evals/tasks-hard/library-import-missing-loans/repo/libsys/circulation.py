"""Issuing, renewing and returning loans. Used by the import and by the holds desk."""

from datetime import date, datetime, timedelta

from libsys.clock import local_date
from libsys.models import Branch, Loan
from libsys.store import LibraryStore


class CirculationError(Exception):
    pass


def due_date(branch: Branch, moment: datetime) -> date:
    """When a loan issued or renewed at `moment` is due back."""
    return local_date(moment, branch.utc_offset) + timedelta(days=branch.loan_days)


def issue(
    store: LibraryStore,
    branch: Branch,
    number: int,
    member: str,
    barcode: str,
    title: str,
    at: datetime,
) -> Loan:
    """Record a loan. Issuing a number again replaces the earlier loan: that's how the
    desk corrects a mistake (wrong member or copy scanned)."""
    if number < 1:
        raise CirculationError(f"loan numbers start at 1, got {number}")
    existing = store.get_loan(branch.code, number)
    if (
        existing is not None
        and existing.issued_at == at
        and existing.member == member
        and existing.barcode == barcode
    ):
        return existing  # the same event seen again
    store.member(member)
    loan = Loan(
        branch=branch.code,
        number=number,
        member=member,
        barcode=barcode,
        title=title.strip(),
        issued_at=at,
        due=due_date(branch, at),
    )
    store.put_loan(loan)
    return loan


def renew(store: LibraryStore, branch: Branch, number: int, at: datetime) -> Loan:
    loan = store.get_loan(branch.code, number)
    if loan is None:
        raise CirculationError(f"no loan {branch.code}-{number} to renew")
    if not loan.is_open:
        raise CirculationError(f"loan {branch.code}-{number} was already returned")
    if at < loan.issued_at:
        raise CirculationError(f"loan {branch.code}-{number} renewed before it was issued")
    new_due = due_date(branch, at)
    if new_due == loan.due:
        return loan  # renewing twice on the same day doesn't use up a renewal
    if loan.renewals >= branch.max_renewals:
        raise CirculationError(
            f"loan {branch.code}-{number} has already been renewed {loan.renewals} times"
        )
    loan.renewals += 1
    loan.due = max(loan.due, new_due)
    return loan


def give_back(store: LibraryStore, branch: Branch, number: int, at: datetime) -> Loan:
    loan = store.get_loan(branch.code, number)
    if loan is None:
        raise CirculationError(f"no loan {branch.code}-{number} to return")
    if loan.returned_at is not None:
        if loan.returned_at == at:
            return loan  # the same event seen again
        raise CirculationError(f"loan {branch.code}-{number} was already returned")
    if at < loan.issued_at:
        raise CirculationError(f"loan {branch.code}-{number} returned before it was issued")
    loan.returned_at = at
    return loan
