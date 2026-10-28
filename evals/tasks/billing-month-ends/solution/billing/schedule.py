"""When subscriptions renew."""

from dataclasses import dataclass
from datetime import date

from billing.calendar import add_months

PLANS = {"monthly": 1, "quarterly": 3, "yearly": 12}


@dataclass(frozen=True)
class Subscription:
    customer: str
    start: date
    plan: str = "monthly"

    @property
    def interval(self) -> int:
        try:
            return PLANS[self.plan]
        except KeyError:
            raise ValueError(f"unknown plan {self.plan!r}") from None


def renewal_dates(sub: Subscription, count: int) -> list[date]:
    """The next `count` renewal dates after the start date.

    A subscription renews on the same day of the month it started on, or on the last day
    of the month when that month is too short.
    """
    # Count from the start each time: stepping from the previous renewal would lose the
    # day of the month after a short month (31 Jan -> 29 Feb -> 29 Mar).
    return [add_months(sub.start, sub.interval * n) for n in range(1, count + 1)]


def next_renewal(sub: Subscription, today: date) -> date:
    """The first renewal strictly after `today`."""
    count = 1
    while True:
        last = renewal_dates(sub, count)[-1]
        if last > today:
            return last
        count += 1
