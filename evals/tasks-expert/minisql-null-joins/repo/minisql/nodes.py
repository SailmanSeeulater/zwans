"""The syntax tree the parser builds and the planner reads.

Expressions are frozen dataclasses, so two expressions written the same way compare equal
and hash alike; the planner relies on that to match a select item against GROUP BY.
"""

from dataclasses import dataclass, field
from typing import Any

AGGREGATES = frozenset({"COUNT", "SUM", "TOTAL", "AVG", "MIN", "MAX"})


class Expr:
    """Base class for expressions."""


@dataclass(frozen=True)
class Literal(Expr):
    value: Any


@dataclass(frozen=True)
class Column(Expr):
    table: str | None
    name: str


@dataclass(frozen=True)
class Slot(Expr):
    """A column after binding: a position in the row the expression is evaluated on."""

    index: int
    label: str


@dataclass(frozen=True)
class Unary(Expr):
    op: str  # "-" or "NOT"
    operand: Expr


@dataclass(frozen=True)
class Binary(Expr):
    op: str  # arithmetic, comparison, "||", "AND", "OR", "IS", "IS NOT"
    left: Expr
    right: Expr


@dataclass(frozen=True)
class IsNull(Expr):
    operand: Expr
    negated: bool = False


@dataclass(frozen=True)
class InList(Expr):
    operand: Expr
    items: tuple[Expr, ...]
    negated: bool = False


@dataclass(frozen=True)
class Between(Expr):
    operand: Expr
    low: Expr
    high: Expr
    negated: bool = False


@dataclass(frozen=True)
class Case(Expr):
    operand: Expr | None
    whens: tuple[tuple[Expr, Expr], ...]
    default: Expr | None


@dataclass(frozen=True)
class Call(Expr):
    name: str
    args: tuple[Expr, ...]
    distinct: bool = False
    star: bool = False

    @property
    def is_aggregate(self) -> bool:
        return self.name in AGGREGATES and (self.star or len(self.args) == 1)


# -- statements


@dataclass
class TableRef:
    name: str
    alias: str | None = None

    @property
    def label(self) -> str:
        return self.alias or self.name


@dataclass
class JoinClause:
    kind: str  # "inner", "left" or "cross"
    table: TableRef
    on: Expr | None


@dataclass
class SelectItem:
    expr: Expr | None  # None for * and t.*
    alias: str | None = None
    star_table: str | None = None


@dataclass
class OrderItem:
    expr: Expr
    descending: bool = False
    nulls: str | None = None  # "first", "last" or None for the default


@dataclass
class Select:
    items: list[SelectItem]
    source: TableRef | None = None
    joins: list[JoinClause] = field(default_factory=list)
    where: Expr | None = None
    group_by: list[Expr] = field(default_factory=list)
    having: Expr | None = None
    order_by: list[OrderItem] = field(default_factory=list)
    limit: Expr | None = None
    offset: Expr | None = None
    distinct: bool = False


@dataclass
class CreateTable:
    name: str
    columns: list[tuple[str, str]]
    if_not_exists: bool = False


@dataclass
class DropTable:
    name: str
    if_exists: bool = False


@dataclass
class Insert:
    table: str
    columns: list[str] | None
    rows: list[list[Expr]]


@dataclass
class Delete:
    table: str
    where: Expr | None


@dataclass
class Update:
    table: str
    assignments: list[tuple[str, Expr]]
    where: Expr | None


@dataclass
class Explain:
    statement: Select


Statement = Select | CreateTable | DropTable | Insert | Delete | Update | Explain


# -- turning expressions back into text, for column headers and EXPLAIN


def render(expr: Expr) -> str:
    if isinstance(expr, Literal):
        if expr.value is None:
            return "NULL"
        if isinstance(expr.value, str):
            return "'" + expr.value.replace("'", "''") + "'"
        return str(expr.value)
    if isinstance(expr, Column):
        return f"{expr.table}.{expr.name}" if expr.table else expr.name
    if isinstance(expr, Slot):
        return expr.label
    if isinstance(expr, Unary):
        if expr.op == "NOT":
            return f"NOT {render(expr.operand)}"
        return f"-{render(expr.operand)}"
    if isinstance(expr, Binary):
        return f"({render(expr.left)} {expr.op} {render(expr.right)})"
    if isinstance(expr, IsNull):
        return f"{render(expr.operand)} IS {'NOT ' if expr.negated else ''}NULL"
    if isinstance(expr, InList):
        items = ", ".join(render(item) for item in expr.items)
        return f"{render(expr.operand)} {'NOT ' if expr.negated else ''}IN ({items})"
    if isinstance(expr, Between):
        word = "NOT BETWEEN" if expr.negated else "BETWEEN"
        return f"{render(expr.operand)} {word} {render(expr.low)} AND {render(expr.high)}"
    if isinstance(expr, Case):
        parts = ["CASE"]
        if expr.operand is not None:
            parts.append(render(expr.operand))
        for condition, result in expr.whens:
            parts.append(f"WHEN {render(condition)} THEN {render(result)}")
        if expr.default is not None:
            parts.append(f"ELSE {render(expr.default)}")
        parts.append("END")
        return " ".join(parts)
    if isinstance(expr, Call):
        if expr.star:
            return f"{expr.name}(*)"
        args = ", ".join(render(arg) for arg in expr.args)
        return f"{expr.name}({'DISTINCT ' if expr.distinct else ''}{args})"
    raise TypeError(f"not an expression: {expr!r}")


def children(expr: Expr) -> tuple[Expr, ...]:
    """The expressions directly inside `expr`."""
    if isinstance(expr, Unary):
        return (expr.operand,)
    if isinstance(expr, Binary):
        return (expr.left, expr.right)
    if isinstance(expr, IsNull):
        return (expr.operand,)
    if isinstance(expr, InList):
        return (expr.operand, *expr.items)
    if isinstance(expr, Between):
        return (expr.operand, expr.low, expr.high)
    if isinstance(expr, Case):
        parts: list[Expr] = [] if expr.operand is None else [expr.operand]
        for condition, result in expr.whens:
            parts += [condition, result]
        if expr.default is not None:
            parts.append(expr.default)
        return tuple(parts)
    if isinstance(expr, Call):
        return expr.args
    return ()


def walk(expr: Expr):
    """Every expression in `expr`, outermost first."""
    stack = [expr]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(children(node)))


def transform(expr: Expr, fn) -> Expr:
    """Rebuild `expr` bottom up; `fn(node)` returns a replacement or None to keep it."""
    replaced = fn(expr)
    if replaced is not None:
        return replaced
    if isinstance(expr, Unary):
        return Unary(expr.op, transform(expr.operand, fn))
    if isinstance(expr, Binary):
        return Binary(expr.op, transform(expr.left, fn), transform(expr.right, fn))
    if isinstance(expr, IsNull):
        return IsNull(transform(expr.operand, fn), expr.negated)
    if isinstance(expr, InList):
        items = tuple(transform(item, fn) for item in expr.items)
        return InList(transform(expr.operand, fn), items, expr.negated)
    if isinstance(expr, Between):
        return Between(
            transform(expr.operand, fn),
            transform(expr.low, fn),
            transform(expr.high, fn),
            expr.negated,
        )
    if isinstance(expr, Case):
        operand = None if expr.operand is None else transform(expr.operand, fn)
        whens = tuple((transform(c, fn), transform(r, fn)) for c, r in expr.whens)
        default = None if expr.default is None else transform(expr.default, fn)
        return Case(operand, whens, default)
    if isinstance(expr, Call):
        return Call(expr.name, tuple(transform(a, fn) for a in expr.args), expr.distinct,
                    expr.star)
    return expr
