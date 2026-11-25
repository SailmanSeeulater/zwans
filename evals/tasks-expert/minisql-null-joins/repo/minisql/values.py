"""SQL values in Python: None is NULL, int is INTEGER, float is REAL, str is TEXT.

How values order, how they're used as grouping keys, and how they print.
"""

from functools import cmp_to_key
from typing import Any, Callable, Iterable

Value = Any  # None | int | float | str


def type_rank(value: Value) -> int:
    """NULL < numbers < text, the order SQLite uses across types."""
    if value is None:
        return 0
    if isinstance(value, str):
        return 2
    return 1


def compare(a: Value, b: Value) -> int:
    """-1, 0 or 1, ordering any two values (NULLs equal to each other and smallest)."""
    ra, rb = type_rank(a), type_rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if a is None or a == b:
        return 0
    return -1 if a < b else 1


class _Null:
    """Stands in for NULL inside a key."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NULL"


def key(values: Iterable[Value]) -> tuple:
    """A hashable key for a tuple of values, as GROUP BY and DISTINCT compare them."""
    return tuple(_Null() if value is None else value for value in values)


def sort_rows(
    rows: list[tuple],
    terms: list[tuple[Callable[[tuple], Value], bool, str | None]],
) -> list[tuple]:
    """`rows` ordered by `terms`: (value of the row, descending?, "first"/"last"/None).

    The sort is stable, so rows that tie on every term keep their order.
    """

    def order(row_a: tuple, row_b: tuple) -> int:
        for value_of, descending, nulls in terms:
            a, b = value_of(row_a), value_of(row_b)
            if a is None or b is None:
                if a is None and b is None:
                    continue
                if nulls is None:
                    nulls_first = descending
                else:
                    nulls_first = nulls == "first"
                return -1 if (a is None) == nulls_first else 1
            result = compare(a, b)
            if result:
                return -result if descending else result
        return 0

    return sorted(rows, key=cmp_to_key(order))


def show(value: Value) -> str:
    """A value as the REPL prints it."""
    if value is None:
        return "NULL"
    if isinstance(value, float):
        return repr(value)
    return str(value)
