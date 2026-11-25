"""Compiles bound expressions into Python functions of a row.

An expression reaches here after the planner has replaced every column by a Slot (its
position in the row) and every aggregate call by the Slot holding its result. `compile_expr`
turns it into a closure, so each row costs one call per node and no tree walking.
"""

from typing import Any, Callable

from minisql.errors import SQLError
from minisql.nodes import (
    Between,
    Binary,
    Call,
    Case,
    Column,
    Expr,
    InList,
    IsNull,
    Literal,
    Slot,
    Unary,
    render,
)
from minisql.values import compare

Row = tuple
Fn = Callable[[Row], Any]

SCALAR_FUNCTIONS = ("COALESCE", "IFNULL", "NULLIF", "ABS", "LENGTH", "UPPER", "LOWER")


def truth(value: Any) -> bool:
    """Whether a value counts as true where a condition is expected."""
    if value is None:
        return False
    if isinstance(value, str):
        return _leading_number(value) != 0
    return value != 0


def _leading_number(text: str) -> float:
    """The number text starts with, as SQLite reads text in a numeric context."""
    text = text.strip()
    best = 0.0
    for end in range(1, len(text) + 1):
        try:
            best = float(text[:end])
        except ValueError:
            continue
    return best


def compile_expr(expr: Expr, base: int = 0) -> Fn:
    """A function of a row. Slot i reads row[i - base]."""
    if isinstance(expr, Literal):
        value = expr.value
        return lambda row: value
    if isinstance(expr, Slot):
        index = expr.index - base
        return lambda row: row[index]
    if isinstance(expr, Column):
        raise SQLError(f"internal error: unbound column {render(expr)}")
    if isinstance(expr, Unary):
        operand = compile_expr(expr.operand, base)
        if expr.op == "NOT":
            return lambda row: _not(operand(row))
        return lambda row: _negate(operand(row))
    if isinstance(expr, Binary):
        return _binary(expr, base)
    if isinstance(expr, IsNull):
        operand = compile_expr(expr.operand, base)
        if expr.negated:
            return lambda row: 0 if operand(row) is None else 1
        return lambda row: 1 if operand(row) is None else 0
    if isinstance(expr, InList):
        return _in_list(expr, base)
    if isinstance(expr, Between):
        operand = compile_expr(expr.operand, base)
        low = compile_expr(expr.low, base)
        high = compile_expr(expr.high, base)

        def between(row: Row) -> Any:
            value = operand(row)
            result = _and(_compare(">=", value, low(row)), _compare("<=", value, high(row)))
            return _not(result) if expr.negated else result

        return between
    if isinstance(expr, Case):
        return _case(expr, base)
    if isinstance(expr, Call):
        return _call(expr, base)
    raise SQLError(f"internal error: cannot compile {expr!r}")


# -- logic


def _not(value: Any) -> int:
    return 0 if truth(value) else 1


def _and(a: Any, b: Any) -> int:
    return 1 if truth(a) and truth(b) else 0


def _or(a: Any, b: Any) -> int:
    return 1 if truth(a) or truth(b) else 0


def _compare(op: str, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    result = compare(a, b)
    if op == "=":
        return int(result == 0)
    if op == "<>":
        return int(result != 0)
    if op == "<":
        return int(result < 0)
    if op == "<=":
        return int(result <= 0)
    if op == ">":
        return int(result > 0)
    if op == ">=":
        return int(result >= 0)
    raise SQLError(f"internal error: unknown comparison {op}")


def _in_list(expr: InList, base: int) -> Fn:
    operand = compile_expr(expr.operand, base)
    items = [compile_expr(item, base) for item in expr.items]
    negated = expr.negated

    def in_list(row: Row) -> Any:
        value = operand(row)
        if value is None:
            return None
        saw_null = False
        for item in items:
            other = item(row)
            if other is None:
                saw_null = True
            elif compare(value, other) == 0:
                return 0 if negated else 1
        if saw_null:
            return None
        return 1 if negated else 0

    return in_list


# -- arithmetic


def _number(value: Any, op: str) -> Any:
    if isinstance(value, str):
        raise SQLError(f"cannot use text {value!r} with {op}")
    return value


def _negate(value: Any) -> Any:
    if value is None:
        return None
    return -_number(value, "-")


def _arithmetic(op: str, a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    a, b = _number(a, op), _number(b, op)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            return None
        if isinstance(a, int) and isinstance(b, int):
            quotient = abs(a) // abs(b)
            return quotient if (a < 0) == (b < 0) else -quotient
        return a / b
    raise SQLError(f"internal error: unknown operator {op}")


def _concat(a: Any, b: Any) -> Any:
    if a is None or b is None:
        return None
    return _text(a) + _text(b)


def _text(value: Any) -> str:
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _binary(expr: Binary, base: int) -> Fn:
    left = compile_expr(expr.left, base)
    right = compile_expr(expr.right, base)
    op = expr.op
    if op == "AND":
        return lambda row: _and(left(row), right(row))
    if op == "OR":
        return lambda row: _or(left(row), right(row))
    if op in ("=", "<>", "<", "<=", ">", ">="):
        return lambda row: _compare(op, left(row), right(row))
    if op in ("IS", "IS NOT"):
        want = 1 if op == "IS" else 0

        def is_(row: Row) -> int:
            a, b = left(row), right(row)
            same = (a is None and b is None) or (
                a is not None and b is not None and compare(a, b) == 0
            )
            return want if same else 1 - want

        return is_
    if op == "||":
        return lambda row: _concat(left(row), right(row))
    return lambda row: _arithmetic(op, left(row), right(row))


# -- CASE and functions


def _case(expr: Case, base: int) -> Fn:
    operand = None if expr.operand is None else compile_expr(expr.operand, base)
    whens = [(compile_expr(c, base), compile_expr(r, base)) for c, r in expr.whens]
    default = None if expr.default is None else compile_expr(expr.default, base)

    def case(row: Row) -> Any:
        subject = None if operand is None else operand(row)
        for condition, result in whens:
            if operand is None:
                hit = truth(condition(row))
            else:
                hit = _compare("=", subject, condition(row)) == 1
            if hit:
                return result(row)
        return None if default is None else default(row)

    return case


def _call(expr: Call, base: int) -> Fn:
    if expr.is_aggregate:
        raise SQLError(f"misuse of aggregate {render(expr)}")
    name = expr.name
    if name not in SCALAR_FUNCTIONS:
        raise SQLError(f"no such function: {name}")
    if expr.distinct:
        raise SQLError(f"DISTINCT is only allowed in aggregates, not {name}")
    args = [compile_expr(arg, base) for arg in expr.args]
    arity = {"IFNULL": 2, "NULLIF": 2, "ABS": 1, "LENGTH": 1, "UPPER": 1, "LOWER": 1}
    if name == "COALESCE":
        if len(args) < 2:
            raise SQLError("COALESCE needs at least two arguments")
    elif len(args) != arity[name]:
        raise SQLError(f"{name} takes {arity[name]} argument(s)")

    if name in ("COALESCE", "IFNULL"):

        def coalesce(row: Row) -> Any:
            for arg in args:
                value = arg(row)
                if value is not None:
                    return value
            return None

        return coalesce
    if name == "NULLIF":
        first, second = args

        def nullif(row: Row) -> Any:
            value = first(row)
            return None if _compare("=", value, second(row)) == 1 else value

        return nullif
    (arg,) = args
    if name == "ABS":
        return lambda row: None if (v := arg(row)) is None else abs(_number(v, "ABS"))
    if name == "LENGTH":
        return lambda row: None if (v := arg(row)) is None else len(_text(v))
    if name == "UPPER":
        return lambda row: None if (v := arg(row)) is None else _text(v).upper()
    return lambda row: None if (v := arg(row)) is None else _text(v).lower()
