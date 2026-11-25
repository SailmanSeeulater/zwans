"""The operators a query plan is built from.

Each operator produces its rows with `rows(stats)`, pulling rows from its children. A row
is a tuple; a join's row is its left row followed by its right row.
"""

from dataclasses import dataclass
from typing import Any, Callable, Iterator

from minisql import aggregates
from minisql.expr import truth
from minisql.values import key, sort_rows

Row = tuple
Fn = Callable[[Row], Any]


@dataclass
class Stats:
    """Counters for the work queries do. `reset()` sets them back to zero."""

    rows_scanned: int = 0  # rows read out of tables
    join_reads: int = 0  # rows joins read from their inputs, both sides
    rows_returned: int = 0  # rows a SELECT gave back

    def reset(self) -> None:
        self.rows_scanned = 0
        self.join_reads = 0
        self.rows_returned = 0


class Node:
    label = "?"

    def rows(self, stats: Stats) -> Iterator[Row]:
        raise NotImplementedError

    def children(self) -> list["Node"]:
        return []

    def detail(self) -> str:
        return ""

    def explain(self, depth: int = 0) -> list[str]:
        detail = self.detail()
        lines = ["  " * depth + self.label + (f" {detail}" if detail else "")]
        for child in self.children():
            lines += child.explain(depth + 1)
        return lines


class OneRow(Node):
    """The single empty row a SELECT without FROM works on."""

    label = "ONE ROW"

    def rows(self, stats: Stats) -> Iterator[Row]:
        yield ()


class Scan(Node):
    label = "SCAN"

    def __init__(self, table, name: str) -> None:
        self.table = table
        self.name = name

    def detail(self) -> str:
        if self.name != self.table.name:
            return f"{self.table.name} AS {self.name}"
        return self.name

    def rows(self, stats: Stats) -> Iterator[Row]:
        for row in list(self.table.rows):
            stats.rows_scanned += 1
            yield tuple(row)


class Filter(Node):
    label = "FILTER"

    def __init__(self, child: Node, predicate: Fn, text: str) -> None:
        self.child = child
        self.predicate = predicate
        self.text = text

    def children(self) -> list[Node]:
        return [self.child]

    def detail(self) -> str:
        return self.text

    def rows(self, stats: Stats) -> Iterator[Row]:
        predicate = self.predicate
        for row in self.child.rows(stats):
            if truth(predicate(row)):
                yield row


class NestedLoopJoin(Node):
    """Joins every left row with every right row the condition accepts."""

    def __init__(self, left: Node, right: Node, kind: str, condition: Fn | None,
                 text: str, right_width: int) -> None:
        self.left = left
        self.right = right
        self.kind = kind
        self.condition = condition
        self.text = text
        self.right_width = right_width

    @property
    def label(self) -> str:
        return f"{self.kind.upper()} JOIN (nested loop)"

    def children(self) -> list[Node]:
        return [self.left, self.right]

    def detail(self) -> str:
        return f"ON {self.text}" if self.text else ""

    def rows(self, stats: Stats) -> Iterator[Row]:
        right_rows = []
        for row in self.right.rows(stats):
            stats.join_reads += 1
            right_rows.append(row)
        padding = (None,) * self.right_width
        condition = self.condition
        for left in self.left.rows(stats):
            stats.join_reads += 1
            matched = False
            for right in right_rows:
                row = left + right
                if condition is None or truth(condition(row)):
                    matched = True
                    yield row
            if not matched and self.kind == "left":
                yield left + padding


class HashJoin(Node):
    """Joins on equal keys: builds a table of the right rows, then probes it."""

    def __init__(self, left: Node, right: Node, kind: str, left_keys: list[Fn],
                 right_keys: list[Fn], residual: Fn | None, text: str,
                 right_width: int) -> None:
        self.left = left
        self.right = right
        self.kind = kind
        self.left_keys = left_keys
        self.right_keys = right_keys
        self.residual = residual
        self.text = text
        self.right_width = right_width

    @property
    def label(self) -> str:
        return f"{self.kind.upper()} JOIN (hash)"

    def children(self) -> list[Node]:
        return [self.left, self.right]

    def detail(self) -> str:
        return f"ON {self.text}"

    def rows(self, stats: Stats) -> Iterator[Row]:
        buckets: dict[tuple, list[Row]] = {}
        for row in self.right.rows(stats):
            stats.join_reads += 1
            values = [fn(row) for fn in self.right_keys]
            buckets.setdefault(key(values), []).append(row)
        padding = (None,) * self.right_width
        residual = self.residual
        for left in self.left.rows(stats):
            stats.join_reads += 1
            values = [fn(left) for fn in self.left_keys]
            matched = False
            for right in buckets.get(key(values), ()):
                row = left + right
                if residual is None or truth(residual(row)):
                    matched = True
                    yield row
            if not matched and self.kind == "left":
                yield left + padding


@dataclass
class AggregateSpec:
    name: str
    argument: Fn | None
    distinct: bool
    star: bool


class Aggregate(Node):
    """Groups rows; each output row is the group's values followed by its aggregates."""

    label = "AGGREGATE"

    def __init__(self, child: Node, groups: list[Fn], specs: list[AggregateSpec],
                 text: str) -> None:
        self.child = child
        self.groups = groups
        self.specs = specs
        self.text = text

    def children(self) -> list[Node]:
        return [self.child]

    def detail(self) -> str:
        return self.text

    def rows(self, stats: Stats) -> Iterator[Row]:
        found: dict[tuple, tuple[list, list]] = {}
        for row in self.child.rows(stats):
            values = [fn(row) for fn in self.groups]
            marker = key(values)
            entry = found.get(marker)
            if entry is None:
                accumulators = [aggregates.make(s.name, s.distinct, s.star) for s in self.specs]
                entry = found[marker] = (values, accumulators)
            for spec, accumulator in zip(self.specs, entry[1]):
                accumulator.add(1 if spec.argument is None else spec.argument(row))
        if not found and not self.groups:
            empty = [aggregates.make(s.name, s.distinct, s.star) for s in self.specs]
            found[()] = ([], empty)
        for values, accumulators in found.values():
            yield tuple(values) + tuple(a.result() for a in accumulators)


class Project(Node):
    label = "PROJECT"

    def __init__(self, child: Node, outputs: list[Fn], text: str) -> None:
        self.child = child
        self.outputs = outputs
        self.text = text

    def children(self) -> list[Node]:
        return [self.child]

    def detail(self) -> str:
        return self.text

    def rows(self, stats: Stats) -> Iterator[Row]:
        outputs = self.outputs
        for row in self.child.rows(stats):
            yield tuple(fn(row) for fn in outputs)


class Distinct(Node):
    label = "DISTINCT"

    def __init__(self, child: Node, width: int) -> None:
        self.child = child
        self.width = width

    def children(self) -> list[Node]:
        return [self.child]

    def rows(self, stats: Stats) -> Iterator[Row]:
        seen = set()
        for row in self.child.rows(stats):
            marker = key(row[: self.width])
            if marker not in seen:
                seen.add(marker)
                yield row


class Sort(Node):
    label = "SORT"

    def __init__(self, child: Node, terms: list[tuple[int, bool, str | None]],
                 text: str) -> None:
        self.child = child
        self.terms = terms
        self.text = text

    def children(self) -> list[Node]:
        return [self.child]

    def detail(self) -> str:
        return self.text

    def rows(self, stats: Stats) -> Iterator[Row]:
        terms = [
            ((lambda row, i=index: row[i]), descending, nulls)
            for index, descending, nulls in self.terms
        ]
        yield from sort_rows(list(self.child.rows(stats)), terms)


class Limit(Node):
    label = "LIMIT"

    def __init__(self, child: Node, limit: int | None, offset: int) -> None:
        self.child = child
        self.limit = limit
        self.offset = offset

    def children(self) -> list[Node]:
        return [self.child]

    def detail(self) -> str:
        text = "all" if self.limit is None else str(self.limit)
        return text + (f" OFFSET {self.offset}" if self.offset else "")

    def rows(self, stats: Stats) -> Iterator[Row]:
        if self.limit is not None and self.limit <= 0:
            return
        given = 0
        for index, row in enumerate(self.child.rows(stats)):
            if index < self.offset:
                continue
            yield row
            given += 1
            if self.limit is not None and given >= self.limit:
                return


class Trim(Node):
    """Drops the extra columns that were only there to sort by."""

    label = "TRIM"

    def __init__(self, child: Node, width: int) -> None:
        self.child = child
        self.width = width

    def children(self) -> list[Node]:
        return [self.child]

    def rows(self, stats: Stats) -> Iterator[Row]:
        for row in self.child.rows(stats):
            yield row[: self.width]
