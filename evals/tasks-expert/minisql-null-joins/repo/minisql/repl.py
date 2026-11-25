"""The interactive shell: `python -m minisql [file.sql ...]`.

Statements end with a semicolon and may span lines. Lines starting with a dot are shell
commands; `.help` lists them.
"""

import sys
from typing import TextIO

from minisql.database import Database, Result
from minisql.errors import SQLError
from minisql.values import show

HELP = """\
.help              this list
.tables            the tables, one per line
.schema [TABLE]    CREATE TABLE statements
.mode box|list|csv how results are printed (box to start with)
.stats             the counters, then reset them
.read FILE         run the statements in FILE
.quit              leave
"""


class Shell:
    def __init__(self, out: TextIO, database: Database | None = None) -> None:
        self.db = database or Database()
        self.out = out
        self.mode = "box"
        self.pending: list[str] = []

    # -- input

    def feed(self, line: str) -> bool:
        """Take one line of input; False once the user asked to quit."""
        stripped = line.strip()
        if not self.pending and stripped.startswith("."):
            return self.command(stripped)
        if not stripped and not self.pending:
            return True
        self.pending.append(line)
        text = "\n".join(self.pending)
        if _complete(text):
            self.pending = []
            self.run(text)
        return True

    @property
    def prompt(self) -> str:
        return "   ...> " if self.pending else "minisql> "

    def run(self, text: str) -> None:
        try:
            self.db.execute(text)
        except SQLError as error:
            self.out.write(f"Error: {error}\n")
            return
        result = self.db.last
        if result.columns:
            self.print_result(result)
        elif result.changed:
            self.out.write(f"({result.changed} row{'s' if result.changed != 1 else ''})\n")

    # -- dot commands

    def command(self, line: str) -> bool:
        name, _, argument = line.partition(" ")
        argument = argument.strip()
        if name in (".quit", ".exit"):
            return False
        if name == ".help":
            self.out.write(HELP)
        elif name == ".tables":
            for table in sorted(self.db.tables):
                self.out.write(table + "\n")
        elif name == ".schema":
            self.schema(argument)
        elif name == ".mode":
            if argument not in ("box", "list", "csv"):
                self.out.write("Error: .mode takes box, list or csv\n")
            else:
                self.mode = argument
        elif name == ".stats":
            stats = self.db.stats
            self.out.write(
                f"rows scanned: {stats.rows_scanned}\n"
                f"join reads: {stats.join_reads}\n"
                f"rows returned: {stats.rows_returned}\n"
            )
            stats.reset()
        elif name == ".read":
            self.read(argument)
        else:
            self.out.write(f"Error: unknown command {name} (try .help)\n")
        return True

    def schema(self, only: str) -> None:
        names = sorted(self.db.tables) if not only else [only.lower()]
        for name in names:
            table = self.db.tables.get(name)
            if table is None:
                self.out.write(f"Error: no such table: {name}\n")
                continue
            columns = ", ".join(f"{c} {kind.upper()}" for c, kind in table.columns)
            self.out.write(f"CREATE TABLE {table.name} ({columns});\n")

    def read(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as error:
            self.out.write(f"Error: {error}\n")
            return
        self.run(text)

    # -- output

    def print_result(self, result: Result) -> None:
        cells = [[show(value) for value in row] for row in result.rows]
        if self.mode == "list":
            self.out.write("|".join(result.columns) + "\n")
            for row in cells:
                self.out.write("|".join(row) + "\n")
            return
        if self.mode == "csv":
            self.out.write(",".join(_csv(c) for c in result.columns) + "\n")
            for row in cells:
                self.out.write(",".join(_csv(c) for c in row) + "\n")
            return
        widths = [len(c) for c in result.columns]
        for row in cells:
            widths = [max(w, len(c)) for w, c in zip(widths, row)]
        rule = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
        self.out.write(rule + "\n")
        self.out.write(_line(result.columns, widths, [False] * len(widths)) + "\n")
        self.out.write(rule + "\n")
        for raw, row in zip(result.rows, cells):
            numeric = [isinstance(v, (int, float)) for v in raw]
            self.out.write(_line(row, widths, numeric) + "\n")
        self.out.write(rule + "\n")


def _line(cells: list[str], widths: list[int], right: list[bool]) -> str:
    parts = [c.rjust(w) if r else c.ljust(w) for c, w, r in zip(cells, widths, right)]
    return "| " + " | ".join(parts) + " |"


def _csv(cell: str) -> str:
    if any(ch in cell for ch in ',"\n'):
        return '"' + cell.replace('"', '""') + '"'
    return cell


def _complete(text: str) -> bool:
    """Whether `text` ends with a semicolon outside quotes and comments."""
    quote = None
    last = ""
    i = 0
    while i < len(text):
        char = text[i]
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif text.startswith("--", i):
            end = text.find("\n", i)
            if end == -1:
                break
            i = end
            continue
        if not char.isspace():
            last = char if not quote else ""
        i += 1
    return quote is None and last == ";"


def main(argv: list[str], stdin: TextIO = sys.stdin, out: TextIO = sys.stdout) -> int:
    shell = Shell(out)
    for path in argv:
        shell.read(path)
    if argv and not stdin.isatty():
        return 0
    interactive = stdin.isatty()
    while True:
        if interactive:
            out.write(shell.prompt)
            out.flush()
        line = stdin.readline()
        if not line:
            break
        if not shell.feed(line.rstrip("\n")):
            break
    return 0
