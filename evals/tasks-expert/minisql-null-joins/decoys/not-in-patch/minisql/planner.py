"""Turns a parsed SELECT into a tree of executor operators.

The steps, in order:

1. Bind: every column name becomes a Slot, its position in the joined row (the tables'
   columns side by side, in FROM order).
2. Split WHERE and every ON into conditions joined by AND, and decide where each one is
   checked: as a table is scanned, by the join that brings in the last table it uses, or
   after a join (see `_place`).
3. Join left to right; a join with `left = right` conditions between its two sides is a
   hash join, anything else a nested loop.
4. Group and aggregate, filter by HAVING, compute the select list, DISTINCT, ORDER BY,
   LIMIT.
"""

from dataclasses import dataclass, field

from minisql import executor as ex
from minisql.errors import SQLError
from minisql.expr import compile_expr
from minisql.nodes import (
    Between,
    Binary,
    Call,
    Column,
    Expr,
    InList,
    IsNull,
    Literal,
    Select,
    Slot,
    Unary,
    render,
    transform,
    walk,
)

STRICT_FUNCTIONS = ("ABS", "LENGTH", "UPPER", "LOWER")


@dataclass
class Source:
    """One table in FROM, with where its columns sit in the joined row."""

    table: object
    name: str
    offset: int

    @property
    def width(self) -> int:
        return len(self.table.columns)

    def column_index(self, column: str) -> int | None:
        for index, (name, _) in enumerate(self.table.columns):
            if name == column:
                return self.offset + index
        return None


@dataclass
class Scope:
    sources: list[Source] = field(default_factory=list)

    @property
    def width(self) -> int:
        return sum(source.width for source in self.sources)

    def source_of(self, index: int) -> int:
        for number, source in enumerate(self.sources):
            if source.offset <= index < source.offset + source.width:
                return number
        raise SQLError(f"internal error: slot {index} is in no table")

    def resolve(self, column: Column) -> Slot:
        if column.table is not None:
            for source in self.sources:
                if source.name == column.table:
                    index = source.column_index(column.name)
                    if index is None:
                        raise SQLError(f"no such column: {column.table}.{column.name}")
                    return Slot(index, f"{column.table}.{column.name}")
            raise SQLError(f"no such table: {column.table}")
        found = [
            (source, index)
            for source in self.sources
            if (index := source.column_index(column.name)) is not None
        ]
        if not found:
            raise SQLError(f"no such column: {column.name}")
        if len(found) > 1:
            raise SQLError(f"ambiguous column name: {column.name}")
        return Slot(found[0][1], column.name)

    def bind(self, expr: Expr) -> Expr:
        return transform(expr, lambda node: self.resolve(node) if isinstance(node, Column)
                         else None)


@dataclass
class Plan:
    root: ex.Node
    columns: list[str]


def plan_select(database, select: Select) -> Plan:
    scope = Scope()
    if select.source is not None:
        refs = [select.source] + [join.table for join in select.joins]
        names = set()
        for ref in refs:
            if ref.label in names:
                raise SQLError(f"table name {ref.label} used twice in FROM; use an alias")
            names.add(ref.label)
            scope.sources.append(Source(database.table(ref.name), ref.label, scope.width))
    node = _from_clause(select, scope)
    return _finish(select, scope, node)


# -- FROM, joins and WHERE


def conjuncts(expr: Expr | None) -> list[Expr]:
    """`expr` split at its top-level ANDs."""
    if expr is None:
        return []
    if isinstance(expr, Binary) and expr.op == "AND":
        return conjuncts(expr.left) + conjuncts(expr.right)
    return [expr]


def _tables_used(expr: Expr, scope: Scope) -> set[int]:
    return {scope.source_of(node.index) for node in walk(expr) if isinstance(node, Slot)}


def _is_strict(expr: Expr, scope: Scope, number: int) -> bool:
    """Whether `expr` is surely NULL when every column of table `number` is NULL."""
    if isinstance(expr, Slot):
        return scope.source_of(expr.index) == number
    if isinstance(expr, Unary):
        return _is_strict(expr.operand, scope, number)
    if isinstance(expr, Binary):
        if expr.op in ("IS", "IS NOT"):
            return False
        if expr.op in ("AND", "OR"):
            return _is_strict(expr.left, scope, number) and _is_strict(expr.right, scope,
                                                                       number)
        return _is_strict(expr.left, scope, number) or _is_strict(expr.right, scope, number)
    if isinstance(expr, (InList, Between)):
        return _is_strict(expr.operand, scope, number)
    if isinstance(expr, Call) and expr.name in STRICT_FUNCTIONS and not expr.is_aggregate:
        return any(_is_strict(arg, scope, number) for arg in expr.args)
    return False


def _rejects_nulls(expr: Expr, scope: Scope, number: int) -> bool:
    """Whether `expr` can't be true for a row whose table `number` columns are all NULL."""
    if isinstance(expr, Binary) and expr.op == "AND":
        return _rejects_nulls(expr.left, scope, number) or _rejects_nulls(expr.right, scope,
                                                                          number)
    if isinstance(expr, Binary) and expr.op == "OR":
        return _rejects_nulls(expr.left, scope, number) and _rejects_nulls(expr.right, scope,
                                                                           number)
    if isinstance(expr, IsNull):
        return expr.negated and _is_strict(expr.operand, scope, number)
    if isinstance(expr, Between) and not expr.negated:
        return any(_is_strict(part, scope, number)
                   for part in (expr.operand, expr.low, expr.high))
    return _is_strict(expr, scope, number)


def _from_clause(select: Select, scope: Scope) -> ex.Node:
    if not scope.sources:
        node: ex.Node = ex.OneRow()
        for condition in conjuncts(select.where):
            condition = scope.bind(condition)
            node = ex.Filter(node, compile_expr(condition), render(condition))
        return node

    count = len(scope.sources)
    kinds = ["first"] + [join.kind for join in select.joins]
    where = [scope.bind(c) for c in conjuncts(select.where)]
    ons = [[]] + [[scope.bind(c) for c in conjuncts(join.on)] for join in select.joins]
    _check_no_aggregates(where, "WHERE")
    for number in range(1, count):
        _check_no_aggregates(ons[number], "ON")

    # A LEFT JOIN whose padded rows WHERE would throw away anyway is an inner join.
    for number in range(1, count):
        if kinds[number] == "left" and any(
            _rejects_nulls(condition, scope, number) for condition in where
        ):
            kinds[number] = "inner"

    at_scan: list[list[Expr]] = [[] for _ in range(count)]
    at_join: list[list[Expr]] = [[] for _ in range(count)]
    after_join: list[list[Expr]] = [[] for _ in range(count)]
    pool = list(where)
    for number in range(1, count):
        if kinds[number] == "left":
            for condition in ons[number]:
                if _tables_used(condition, scope) == {number}:
                    at_scan[number].append(condition)
                else:
                    at_join[number].append(condition)
        else:
            pool += ons[number]
            if ons[number]:
                kinds[number] = "inner"
    nullable = {number for number in range(1, count) if kinds[number] == "left"}
    for condition in pool:
        _place(condition, _tables_used(condition, scope), kinds, nullable,
               at_scan, at_join, after_join)

    node = _scan(scope, 0, at_scan[0])
    for number in range(1, count):
        right = _scan(scope, number, at_scan[number])
        node = _join(scope, number, kinds[number], node, right, at_join[number])
        for condition in after_join[number]:
            node = ex.Filter(node, compile_expr(condition), render(condition))
    return node


def _place(condition, used, kinds, nullable, at_scan, at_join, after_join) -> None:
    """Decide where a WHERE (or inner join ON) condition is checked."""
    if not used:
        at_scan[0].append(condition)
        return
    if len(used) == 1:
        (number,) = used
        if number not in nullable:
            at_scan[number].append(condition)
            return
    last = max(used)
    if last > 0 and kinds[last] in ("inner", "cross"):
        at_join[last].append(condition)
        kinds[last] = "inner"
    elif last == 0:
        at_scan[0].append(condition)
    else:
        after_join[last].append(condition)


def _scan(scope: Scope, number: int, conditions: list[Expr]) -> ex.Node:
    source = scope.sources[number]
    node: ex.Node = ex.Scan(source.table, source.name)
    for condition in conditions:
        node = ex.Filter(node, compile_expr(condition, source.offset), render(condition))
    return node


def _join(scope: Scope, number: int, kind: str, left: ex.Node, right: ex.Node,
          conditions: list[Expr]) -> ex.Node:
    source = scope.sources[number]
    left_keys: list[Expr] = []
    right_keys: list[Expr] = []
    rest: list[Expr] = []
    for condition in conditions:
        if isinstance(condition, Binary) and condition.op == "=":
            a = _tables_used(condition.left, scope)
            b = _tables_used(condition.right, scope)
            if a and b and max(a) < number and b == {number}:
                left_keys.append(condition.left)
                right_keys.append(condition.right)
                continue
            if a and b and max(b) < number and a == {number}:
                left_keys.append(condition.right)
                right_keys.append(condition.left)
                continue
        rest.append(condition)
    text = " AND ".join(render(c) for c in conditions)
    residual = _all_of(rest)
    residual_fn = None if residual is None else compile_expr(residual)
    if left_keys:
        return ex.HashJoin(
            left,
            right,
            kind,
            [compile_expr(k) for k in left_keys],
            [compile_expr(k, source.offset) for k in right_keys],
            residual_fn,
            text,
            source.width,
        )
    return ex.NestedLoopJoin(left, right, kind, residual_fn, text, source.width)


def _all_of(conditions: list[Expr]) -> Expr | None:
    if not conditions:
        return None
    combined = conditions[0]
    for condition in conditions[1:]:
        combined = Binary("AND", combined, condition)
    return combined


def _check_no_aggregates(conditions: list[Expr], where: str) -> None:
    for condition in conditions:
        for node in walk(condition):
            if isinstance(node, Call) and node.is_aggregate:
                raise SQLError(f"misuse of aggregate {render(node)} in {where}")


# -- grouping, the select list, ORDER BY and LIMIT


def _expand_items(select: Select, scope: Scope) -> list[tuple[Expr, str, str | None]]:
    """The select list with stars expanded: (bound expression, header, alias)."""
    items: list[tuple[Expr, str, str | None]] = []
    for item in select.items:
        if item.expr is not None:
            bound = scope.bind(item.expr)
            items.append((bound, item.alias or _header(item.expr), item.alias))
            continue
        sources = scope.sources
        if item.star_table is not None:
            sources = [s for s in sources if s.name == item.star_table]
            if not sources:
                raise SQLError(f"no such table: {item.star_table}")
        if not scope.sources:
            raise SQLError("* needs a FROM clause")
        for source in sources:
            for index, (name, _) in enumerate(source.table.columns):
                items.append((Slot(source.offset + index, f"{source.name}.{name}"), name, None))
    return items


def _header(expr: Expr) -> str:
    if isinstance(expr, Column):
        return expr.name
    text = render(expr)
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    return text


def _aggregate_calls(exprs: list[Expr]) -> list[Call]:
    found: list[Call] = []
    for expr in exprs:
        for node in walk(expr):
            if isinstance(node, Call) and node.is_aggregate and node not in found:
                for arg in node.args:
                    for inner in walk(arg):
                        if isinstance(inner, Call) and inner.is_aggregate:
                            raise SQLError(f"aggregate inside aggregate: {render(node)}")
                found.append(node)
    return found


def _order_terms(select: Select, scope: Scope, items):
    """ORDER BY terms as (output position or bound expression, descending, nulls)."""
    terms = []
    for item in select.order_by:
        expr = item.expr
        if isinstance(expr, Literal) and isinstance(expr.value, int):
            if not 1 <= expr.value <= len(items):
                raise SQLError(f"ORDER BY term {expr.value} is out of range")
            terms.append((expr.value - 1, item.descending, item.nulls))
            continue
        if isinstance(expr, Column) and expr.table is None:
            explicit = [i for i, (_, _, alias) in enumerate(items) if alias == expr.name]
            if explicit:
                terms.append((explicit[0], item.descending, item.nulls))
                continue
        bound = scope.bind(expr)
        positions = [i for i, (output, _, _) in enumerate(items) if output == bound]
        if positions:
            terms.append((positions[0], item.descending, item.nulls))
        else:
            terms.append((bound, item.descending, item.nulls))
    return terms


def _finish(select: Select, scope: Scope, node: ex.Node) -> Plan:
    items = _expand_items(select, scope)
    headers = [name for _, name, _ in items]
    outputs = [expr for expr, _, _ in items]
    terms = _order_terms(select, scope, items)
    extra = [term[0] for term in terms if not isinstance(term[0], int)]
    having = None if select.having is None else scope.bind(select.having)
    groups = [_group_term(g, select, scope, items) for g in select.group_by]

    calls = _aggregate_calls(outputs + extra + ([having] if having is not None else []))
    if groups or calls or having is not None:
        if having is not None and not groups and not calls:
            raise SQLError("HAVING needs GROUP BY or an aggregate")
        for group in groups:
            for inner in walk(group):
                if isinstance(inner, Call) and inner.is_aggregate:
                    raise SQLError("aggregate in GROUP BY")
        node = ex.Aggregate(
            node,
            [compile_expr(g) for g in groups],
            [
                ex.AggregateSpec(
                    call.name,
                    None if call.star else compile_expr(call.args[0]),
                    call.distinct,
                    call.star,
                )
                for call in calls
            ],
            ", ".join(render(g) for g in groups) or "all rows",
        )
        replacements: dict[Expr, Slot] = {}
        for index, group in enumerate(groups):
            replacements[group] = Slot(index, render(group))
        for index, call in enumerate(calls):
            replacements[call] = Slot(len(groups) + index, render(call))

        def regroup(expr: Expr) -> Expr:
            def swap(inner: Expr) -> Expr | None:
                if inner in replacements:
                    return replacements[inner]
                if isinstance(inner, Slot):
                    raise SQLError(
                        f"column {inner.label} must appear in GROUP BY or in an aggregate"
                    )
                return None

            return transform(expr, swap)

        outputs = [regroup(e) for e in outputs]
        extra = [regroup(e) for e in extra]
        if having is not None:
            having = regroup(having)
            node = ex.Filter(node, compile_expr(having), "HAVING " + render(having))

    projected = outputs + extra
    node = ex.Project(node, [compile_expr(e) for e in projected],
                      ", ".join(render(e) for e in projected))
    if select.distinct:
        if extra:
            raise SQLError("with DISTINCT, ORDER BY terms must be in the select list")
        node = ex.Distinct(node, len(outputs))
    if terms:
        sort_terms = []
        next_extra = len(outputs)
        texts = []
        for target, descending, nulls in terms:
            if isinstance(target, int):
                position = target
            else:
                position = next_extra
                next_extra += 1
            sort_terms.append((position, descending, nulls))
            texts.append(f"#{position + 1}{' DESC' if descending else ''}"
                         f"{f' NULLS {nulls.upper()}' if nulls else ''}")
        node = ex.Sort(node, sort_terms, ", ".join(texts))
    if select.limit is not None:
        limit = _constant_int(select.limit, "LIMIT")
        offset = 0 if select.offset is None else max(0, _constant_int(select.offset, "OFFSET"))
        node = ex.Limit(node, None if limit < 0 else limit, offset)
    if extra:
        node = ex.Trim(node, len(outputs))
    return Plan(node, headers)


def _group_term(expr: Expr, select: Select, scope: Scope, items) -> Expr:
    if isinstance(expr, Literal) and isinstance(expr.value, int):
        if not 1 <= expr.value <= len(items):
            raise SQLError(f"GROUP BY term {expr.value} is out of range")
        return items[expr.value - 1][0]
    if isinstance(expr, Column) and expr.table is None:
        for bound, _, alias in items:
            if alias == expr.name:
                return bound
    return scope.bind(expr)


def _constant_int(expr: Expr, what: str) -> int:
    value = compile_expr(expr)(())
    if not isinstance(value, int):
        raise SQLError(f"{what} must be an integer")
    return value
