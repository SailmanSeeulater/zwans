"""The Database tool: look at a project's data with SQL, without being able to change it.

"Why is this record wrong" usually needs the record. This lists a database's tables and
columns, and runs a query, returning the rows as a table: at most MAX_ROWS of them, so a
query without a LIMIT doesn't fill the conversation.

It only reads. A SQLite file is opened read-only. Postgres is reached through psql with the
address in an environment variable (DATABASE_URL unless the call names another), so the
password never passes through the conversation, and the query runs alone in a read-only
transaction: one statement, which can't end the transaction to start a writable one. To
change data, the model uses Bash, which the policy judges like any other command.

Both run where commands run, through the executor, as sqlite3 and psql.
"""

import csv
import io
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from zwans.executor.base import CommandResult
from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_ROWS = 200
MAX_CELL = 120  # characters of one value
MAX_SCHEMA_CHARS = 20_000
TIMEOUT = 60.0
NOT_FOUND = (126, 127)
READING = ("select", "with", "values", "table", "explain", "show", "pragma")
ROWS = ("select", "with", "values", "table")  # queries that can be wrapped in a LIMIT
SQLITE_SCHEMA = (
    "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'view') "
    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
)
POSTGRES_SCHEMA = (
    "SELECT c.table_schema || '.' || c.table_name AS table_name, c.column_name, c.data_type, "
    "c.is_nullable FROM information_schema.columns c "
    "WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY c.table_schema, c.table_name, c.ordinal_position"
)


class DatabaseInput(BaseModel):
    path: str | None = Field(
        default=None, description="A SQLite database file, relative to the workspace root."
    )
    env: str | None = Field(
        default=None,
        description="For Postgres: the environment variable holding the connection address, "
        "as DATABASE_URL (the default when no path is given). Never the address itself.",
    )
    query: str = Field(
        default="",
        description="One SQL statement that reads: SELECT, WITH, EXPLAIN, SHOW or PRAGMA. "
        "Leave it empty to list the tables and their columns.",
    )


class DatabaseTool:
    name = "Database"
    description = (
        "Look at a database: leave query empty to list its tables and columns, or run one "
        "SQL statement that reads and get the rows as a table (at most 200; add a LIMIT or "
        "WHERE for the rest). A SQLite file by path, or Postgres through an environment "
        "variable holding the address (DATABASE_URL by default). It can't change data: use "
        "Bash with sqlite3 or psql for that."
    )
    input_model = DatabaseInput
    read_only = True  # SQLite opened read-only, Postgres in a read-only transaction

    async def run(self, args: DatabaseInput, ctx: ToolContext) -> ToolOutput:
        query = _one_statement(args.query)
        if args.path:
            path = ctx.executor.relative(args.path)
            if not query:
                return ToolOutput(content=await _sqlite_schema(ctx, path))
            rows = await _sqlite(ctx, path, _limited(query))
            where = path
        else:
            env = (args.env or "DATABASE_URL").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
                raise ToolError(
                    "env names the environment variable that holds the address, as "
                    "DATABASE_URL, not the address itself."
                )
            if not query:
                return ToolOutput(
                    content=_postgres_schema(await _postgres(ctx, env, POSTGRES_SCHEMA))
                )
            rows = await _postgres(ctx, env, _limited(query))
            where = f"${env}"
        return ToolOutput(content=_table(rows, where))


def _one_statement(query: str) -> str:
    """The query without its last semicolon, refused if it holds another statement or
    doesn't read."""
    text = query.strip().rstrip(";").strip()
    if not text:
        return ""
    bare = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", "''", text, flags=re.S)
    if ";" in bare:
        raise ToolError("Send one statement at a time.")
    first = bare.split(None, 1)[0].lower().lstrip("(")
    if first not in READING:
        raise ToolError(
            f"Database only reads, and {first.upper()} doesn't. To change data, use Bash with "
            "sqlite3 or psql, which the policy judges like any other command."
        )
    return text


def _limited(query: str) -> str:
    """A query that returns rows, cut at one more than MAX_ROWS, to tell there were more."""
    first = query.split(None, 1)[0].lower().lstrip("(")
    if first in ROWS:
        return f"SELECT * FROM ({query}) AS zwans_rows LIMIT {MAX_ROWS + 1}"
    return query


async def _run(ctx: ToolContext, argv: list[str], program: str) -> CommandResult:
    try:
        result = await ctx.executor.run(argv, timeout=TIMEOUT)
    except FileNotFoundError:
        raise ToolError(f"{program} isn't installed where commands run.") from None
    if result.exit_code in NOT_FOUND:
        raise ToolError(f"{program} isn't installed where commands run.")
    if result.timed_out:
        raise ToolError(f"The query was stopped after {TIMEOUT:.0f}s.")
    return result


async def _sqlite(ctx: ToolContext, path: str, query: str) -> list[dict[str, Any]]:
    result = await _run(ctx, ["sqlite3", "-readonly", "-json", path, query], "sqlite3")
    output = result.output.strip()
    if result.exit_code != 0:
        if "unable to open" in output or "no such file" in output.lower():
            raise ToolError(f"There is no SQLite database at {path}.")
        raise ToolError(f"SQLite: {output or 'the query failed'}")
    if not output:
        return []
    try:
        rows = json.loads(output)
    except ValueError:
        raise ToolError(f"SQLite: {output[:500]}") from None
    return rows if isinstance(rows, list) else []


async def _sqlite_schema(ctx: ToolContext, path: str) -> str:
    rows = await _sqlite(ctx, path, SQLITE_SCHEMA)
    if not rows:
        return f"{path} has no tables."
    parts = [f"{path}: {len(rows)} tables and views."]
    for row in rows:
        sql = " ".join(str(row.get("sql") or "").split())
        parts.append(f"\n{sql};")
    return _cut("\n".join(parts), MAX_SCHEMA_CHARS)


async def _postgres(ctx: ToolContext, env: str, query: str) -> list[dict[str, Any]]:
    # The address stays in the variable, read by the shell; the query is one statement,
    # in a transaction that can only read.
    quoted = query.replace("'", "'\"'\"'")
    command = (
        f'psql "${{{env}:?{env} is not set}}" -X -q -v ON_ERROR_STOP=1 --csv '
        f"-c 'BEGIN READ ONLY' -c '{quoted}' -c 'ROLLBACK'"
    )
    try:
        result = await ctx.executor.run_shell(command, timeout=TIMEOUT)
    except FileNotFoundError:
        raise ToolError("psql isn't installed where commands run.") from None
    output = result.output.strip()
    # Checked first: the shell gives a missing variable the same exit code as a missing program.
    if f"{env} is not set" in output:
        raise ToolError(f"{env} isn't set where commands run, so there's no database to reach.")
    if result.exit_code in NOT_FOUND or "psql: command not found" in output:
        raise ToolError("psql isn't installed where commands run (on a Mac: brew install libpq).")
    if result.exit_code != 0:
        raise ToolError(f"Postgres: {output or 'the query failed'}")
    lines = [line for line in output.splitlines() if line not in ("BEGIN", "ROLLBACK")]
    if not lines:
        return []
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    return list(reader)


def _postgres_schema(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "The database has no tables of its own."
    tables: dict[str, list[str]] = {}
    for row in rows:
        null = "" if row.get("is_nullable") == "YES" else " not null"
        column = f"{row.get('column_name')} {row.get('data_type')}{null}"
        tables.setdefault(str(row.get("table_name")), []).append(column)
    parts = [f"{len(tables)} tables and views."]
    parts += [f"\n{name}({', '.join(columns)})" for name, columns in tables.items()]
    return _cut("\n".join(parts), MAX_SCHEMA_CHARS)


def _table(rows: list[dict[str, Any]], where: str) -> str:
    if not rows:
        return f"No rows ({where})."
    more = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    columns = list(rows[0].keys())
    cells = [[_cell(row.get(column)) for column in columns] for row in rows]
    widths = [
        max(len(column), *(len(line[n]) for line in cells)) for n, column in enumerate(columns)
    ]
    lines = [
        " | ".join(column.ljust(widths[n]) for n, column in enumerate(columns)).rstrip(),
        "-+-".join("-" * width for width in widths),
        *(" | ".join(v.ljust(widths[n]) for n, v in enumerate(line)).rstrip() for line in cells),
    ]
    count = f"The first {MAX_ROWS} rows; there are more" if more else f"{len(rows)} rows"
    return "\n".join(lines) + f"\n({count}, from {where}.)"


def _cell(value: object) -> str:
    if value is None:
        return "NULL"
    text = " ".join(str(value).split()) if not isinstance(value, str) else value
    text = text.replace("\n", "\\n")
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[... the rest isn't shown]"
