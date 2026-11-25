"""Tables and the Database object that runs statements against them."""

from dataclasses import dataclass, field
from typing import Any

from minisql.errors import SQLError
from minisql.executor import Stats
from minisql.expr import compile_expr, truth
from minisql.nodes import (
    CreateTable,
    Delete,
    DropTable,
    Explain,
    Expr,
    Insert,
    Select,
    Statement,
    Update,
    render,
    walk,
)
from minisql.nodes import Column as ColumnRef
from minisql.parser import parse
from minisql.planner import Scope, Source, plan_select


@dataclass
class Table:
    name: str
    columns: list[tuple[str, str]]  # (name, "integer" or "text")
    rows: list[list[Any]] = field(default_factory=list)

    def column_names(self) -> list[str]:
        return [name for name, _ in self.columns]

    def check(self, column: str, value: Any) -> Any:
        """`value` if it may go in `column`, else SQLError."""
        kind = dict(self.columns)[column]
        if value is None:
            return None
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return value
        if kind == "text" and isinstance(value, str):
            return value
        raise SQLError(f"{self.name}.{column} is {kind.upper()}; cannot store {value!r}")


@dataclass
class Result:
    """What a statement gave back: column names and rows (empty for anything but SELECT)."""

    columns: list[str]
    rows: list[tuple]
    changed: int = 0


class Database:
    def __init__(self) -> None:
        self.tables: dict[str, Table] = {}
        self.stats = Stats()
        self.last = Result([], [])

    # -- the API

    def execute(self, sql: str) -> list[tuple]:
        """Run every statement in `sql`; the rows of the last one."""
        statements = parse(sql)
        if not statements:
            raise SQLError("no statement to run")
        for statement in statements:
            self.last = self.run(statement)
        return self.last.rows

    def columns(self) -> list[str]:
        """The column names of the last statement's result."""
        return self.last.columns

    def table(self, name: str) -> Table:
        try:
            return self.tables[name.lower()]
        except KeyError:
            raise SQLError(f"no such table: {name}") from None

    # -- statements

    def run(self, statement: Statement) -> Result:
        if isinstance(statement, Select):
            plan = plan_select(self, statement)
            rows = list(plan.root.rows(self.stats))
            self.stats.rows_returned += len(rows)
            return Result(plan.columns, rows)
        if isinstance(statement, Explain):
            plan = plan_select(self, statement.statement)
            return Result(["plan"], [(line,) for line in plan.root.explain()])
        if isinstance(statement, CreateTable):
            return self._create(statement)
        if isinstance(statement, DropTable):
            if statement.name not in self.tables:
                if statement.if_exists:
                    return Result([], [])
                raise SQLError(f"no such table: {statement.name}")
            del self.tables[statement.name]
            return Result([], [])
        if isinstance(statement, Insert):
            return self._insert(statement)
        if isinstance(statement, Delete):
            return self._delete(statement)
        if isinstance(statement, Update):
            return self._update(statement)
        raise SQLError(f"cannot run {type(statement).__name__}")

    def _create(self, statement: CreateTable) -> Result:
        if statement.name in self.tables:
            if statement.if_not_exists:
                return Result([], [])
            raise SQLError(f"table {statement.name} already exists")
        names = [name for name, _ in statement.columns]
        if len(set(names)) != len(names):
            raise SQLError(f"duplicate column name in {statement.name}")
        self.tables[statement.name] = Table(statement.name, list(statement.columns))
        return Result([], [])

    def _insert(self, statement: Insert) -> Result:
        table = self.table(statement.table)
        columns = statement.columns or table.column_names()
        for column in columns:
            if column not in table.column_names():
                raise SQLError(f"table {table.name} has no column {column}")
        new_rows = []
        for values in statement.rows:
            if len(values) != len(columns):
                raise SQLError(f"{len(values)} values for {len(columns)} columns")
            given = dict(zip(columns, (_constant(v) for v in values)))
            new_rows.append(
                [table.check(name, given.get(name)) for name in table.column_names()]
            )
        table.rows.extend(new_rows)
        return Result([], [], len(new_rows))

    def _row_scope(self, table: Table) -> Scope:
        return Scope([Source(table, table.name, 0)])

    def _delete(self, statement: Delete) -> Result:
        table = self.table(statement.table)
        if statement.where is None:
            count = len(table.rows)
            table.rows.clear()
            return Result([], [], count)
        condition = compile_expr(self._row_scope(table).bind(statement.where))
        keep = [row for row in table.rows if not truth(condition(tuple(row)))]
        count = len(table.rows) - len(keep)
        table.rows[:] = keep
        return Result([], [], count)

    def _update(self, statement: Update) -> Result:
        table = self.table(statement.table)
        scope = self._row_scope(table)
        names = table.column_names()
        changes = []
        for column, expr in statement.assignments:
            if column not in names:
                raise SQLError(f"table {table.name} has no column {column}")
            changes.append((names.index(column), column, compile_expr(scope.bind(expr))))
        condition = None
        if statement.where is not None:
            condition = compile_expr(scope.bind(statement.where))
        count = 0
        for row in table.rows:
            current = tuple(row)
            if condition is not None and not truth(condition(current)):
                continue
            for index, column, value_of in changes:
                row[index] = table.check(column, value_of(current))
            count += 1
        return Result([], [], count)


def _constant(expr: Expr) -> Any:
    for node in walk(expr):
        if isinstance(node, ColumnRef):
            raise SQLError(f"VALUES can't use columns: {render(expr)}")
    return compile_expr(expr)(())
