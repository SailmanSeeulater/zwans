"""Expanding cadence rules into dates. SPEC.md defines the rule language."""

from collections.abc import Iterable
from datetime import date

from cadence.holidays import Holidays


class RuleError(ValueError):
    """A cadence rule that does not follow SPEC.md."""


def expand(
    rule: str, start: date, end: date, holidays: Holidays | Iterable[date] = ()
) -> list[date]:
    """The dates of the rule's occurrences from start to end, both inclusive."""
    raise NotImplementedError
