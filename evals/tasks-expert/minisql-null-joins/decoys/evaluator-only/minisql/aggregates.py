"""Aggregate functions: one accumulator per group, fed one value per row."""

from typing import Any

from minisql.errors import SQLError
from minisql.values import compare, key


class Accumulator:
    """Collects the values of one aggregate over one group."""

    def __init__(self, distinct: bool = False) -> None:
        self.distinct = distinct
        self.seen: set = set()

    def add(self, value: Any) -> None:
        if value is None:
            return
        if self.distinct:
            marker = key((value,))
            if marker in self.seen:
                return
            self.seen.add(marker)
        self.step(value)

    def step(self, value: Any) -> None:
        raise NotImplementedError

    def result(self) -> Any:
        raise NotImplementedError


class CountRows(Accumulator):
    """COUNT(*): every row, whatever is in it."""

    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.count = 0

    def add(self, value: Any) -> None:
        self.count += 1

    def result(self) -> int:
        return self.count


class Count(Accumulator):
    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.count = 0

    def step(self, value: Any) -> None:
        self.count += 1

    def result(self) -> int:
        return self.count


class Sum(Accumulator):
    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.total: Any = None

    def step(self, value: Any) -> None:
        _check_number(value, "SUM")
        self.total = value if self.total is None else self.total + value

    def result(self) -> Any:
        return self.total


class Total(Accumulator):
    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.total = 0.0

    def step(self, value: Any) -> None:
        _check_number(value, "TOTAL")
        self.total += value

    def result(self) -> float:
        return float(self.total)


class Avg(Accumulator):
    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.total: Any = 0
        self.count = 0

    def step(self, value: Any) -> None:
        _check_number(value, "AVG")
        self.total += value
        self.count += 1

    def result(self) -> Any:
        if self.count == 0:
            return None
        return self.total / self.count


class Min(Accumulator):
    def __init__(self, distinct: bool = False) -> None:
        super().__init__(distinct)
        self.best: Any = None
        self.empty = True

    def step(self, value: Any) -> None:
        if self.empty or compare(value, self.best) < 0:
            self.best = value
            self.empty = False

    def result(self) -> Any:
        return self.best


class Max(Min):
    def step(self, value: Any) -> None:
        if self.empty or compare(value, self.best) > 0:
            self.best = value
            self.empty = False


KINDS: dict[str, type[Accumulator]] = {
    "COUNT": Count,
    "SUM": Sum,
    "TOTAL": Total,
    "AVG": Avg,
    "MIN": Min,
    "MAX": Max,
}


def make(name: str, distinct: bool, star: bool) -> Accumulator:
    if star:
        return CountRows()
    try:
        return KINDS[name](distinct)
    except KeyError:
        raise SQLError(f"no such aggregate: {name}") from None


def _check_number(value: Any, name: str) -> None:
    if isinstance(value, str):
        raise SQLError(f"{name} of text {value!r}")
