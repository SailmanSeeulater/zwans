"""Daylight-saving rules: when summer time starts and ends in a given year, in UTC."""

from datetime import UTC, date, datetime, timedelta

SUNDAY = 6


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The n-th `weekday` (0 = Monday) of a month; n = -1 is the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    following = date(year + month // 12, month % 12 + 1, 1)
    last = following - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


class Rule:
    name = "none"

    def summer(self, year: int, standard: timedelta) -> tuple[datetime, datetime] | None:
        """(start, end) of summer time in `year`, as UTC instants, or None."""
        return None


class EURule(Rule):
    name = "eu"

    def summer(self, year: int, standard: timedelta) -> tuple[datetime, datetime] | None:
        start = nth_weekday(year, 3, SUNDAY, -1)
        end = nth_weekday(year, 10, SUNDAY, -1)
        return (
            datetime(start.year, start.month, start.day, 1, tzinfo=UTC),
            datetime(end.year, end.month, end.day, 1, tzinfo=UTC),
        )


class USRule(Rule):
    name = "us"

    def summer(self, year: int, standard: timedelta) -> tuple[datetime, datetime] | None:
        start = nth_weekday(year, 3, SUNDAY, 2)
        end = nth_weekday(year, 11, SUNDAY, 1)
        # 02:00 local standard time in March, 02:00 local summer time in November.
        start_utc = datetime(start.year, start.month, start.day, 2, tzinfo=UTC) - standard
        end_utc = datetime(end.year, end.month, end.day, 2, tzinfo=UTC) - (
            standard + timedelta(hours=1)
        )
        return start_utc, end_utc


RULES: dict[str, Rule] = {rule.name: rule for rule in (Rule(), EURule(), USRule())}
