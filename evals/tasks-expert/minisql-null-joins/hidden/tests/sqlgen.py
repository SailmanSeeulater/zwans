"""Random tables full of NULLs, and random queries within the grammar the README lists.

Everything is generated as SQL text that both minisql and SQLite accept, and every column
is always written with its table's alias, so names never resolve differently.
"""

import random
from dataclasses import dataclass

TABLES = ("t1", "t2", "t3")
INT_COLUMNS = ("id", "k", "v")
TEXT_COLUMNS = ("s",)
SCHEMA = "(id INTEGER, k INTEGER, v INTEGER, s TEXT)"


def _sql(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value + "'"
    return str(value)


def setup_script(rng: random.Random) -> list[str]:
    """CREATE TABLE and INSERT statements for three small tables with NULLs in them."""
    statements = []
    for table in TABLES:
        statements.append(f"CREATE TABLE {table} {SCHEMA}")
        rows = []
        for number in range(1, rng.randint(0, 9) + 1):
            k = None if rng.random() < 0.25 else rng.randint(0, 3)
            v = None if rng.random() < 0.3 else rng.randint(-3, 9)
            s = None if rng.random() < 0.3 else rng.choice("abc")
            ident = None if rng.random() < 0.08 else number
            rows.append(f"({_sql(ident)}, {_sql(k)}, {_sql(v)}, {_sql(s)})")
        if rows:
            statements.append(f"INSERT INTO {table} VALUES {', '.join(rows)}")
    return statements


@dataclass
class Query:
    sql: str
    order_positions: list[int]  # output columns the result is ordered by, if any
    total_order: bool  # the ORDER BY covers every output column


class QueryMaker:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.aliases: list[str] = ["a"]

    # -- leaves

    def int_column(self) -> str:
        return f"{self.rng.choice(self.aliases)}.{self.rng.choice(INT_COLUMNS)}"

    def text_column(self) -> str:
        return f"{self.rng.choice(self.aliases)}.s"

    def int_literal(self) -> str:
        return "NULL" if self.rng.random() < 0.1 else str(self.rng.randint(-2, 6))

    def text_literal(self) -> str:
        return "NULL" if self.rng.random() < 0.1 else f"'{self.rng.choice('abcd')}'"

    # -- expressions

    def int_expr(self, depth: int = 0) -> str:
        rng = self.rng
        roll = rng.random()
        if depth >= 2 or roll < 0.45:
            return self.int_column() if rng.random() < 0.75 else self.int_literal()
        if roll < 0.62:
            op = rng.choice(["+", "-", "*", "+", "/"])
            return f"({self.int_expr(depth + 1)} {op} {self.int_expr(depth + 1)})"
        if roll < 0.7:
            name = rng.choice(["COALESCE", "IFNULL"])
            return f"{name}({self.int_expr(depth + 1)}, {self.int_expr(depth + 1)})"
        if roll < 0.75:
            return f"NULLIF({self.int_expr(depth + 1)}, {self.int_expr(depth + 1)})"
        if roll < 0.8:
            return f"ABS({self.int_expr(depth + 1)})"
        if roll < 0.84:
            return f"LENGTH({self.text_expr(depth + 1)})"
        if roll < 0.88:
            return f"(- {self.int_expr(depth + 1)})"
        if roll < 0.95:
            otherwise = f" ELSE {self.int_expr(depth + 1)}" if rng.random() < 0.6 else ""
            return (f"CASE WHEN {self.predicate(depth + 1)} THEN {self.int_expr(depth + 1)}"
                    f"{otherwise} END")
        return (f"CASE {self.int_expr(depth + 1)} WHEN {self.int_literal()} THEN "
                f"{self.int_expr(depth + 1)} ELSE {self.int_expr(depth + 1)} END")

    def text_expr(self, depth: int = 0) -> str:
        rng = self.rng
        roll = rng.random()
        if depth >= 2 or roll < 0.6:
            return self.text_column() if rng.random() < 0.7 else self.text_literal()
        if roll < 0.75:
            return f"COALESCE({self.text_expr(depth + 1)}, {self.text_expr(depth + 1)})"
        if roll < 0.85:
            return f"({self.text_expr(depth + 1)} || {self.text_expr(depth + 1)})"
        if roll < 0.92:
            return f"UPPER({self.text_expr(depth + 1)})"
        return f"NULLIF({self.text_expr(depth + 1)}, {self.text_literal()})"

    def predicate(self, depth: int = 0) -> str:
        rng = self.rng
        roll = rng.random()
        if depth >= 3:
            roll = rng.random() * 0.6
        if roll < 0.22:
            op = rng.choice(["=", "<>", "<", "<=", ">", ">="])
            return f"({self.int_expr(depth + 1)} {op} {self.int_expr(depth + 1)})"
        if roll < 0.3:
            op = rng.choice(["=", "<>", "<", ">="])
            return f"({self.text_expr(depth + 1)} {op} {self.text_expr(depth + 1)})"
        if roll < 0.38:
            word = rng.choice(["IS NULL", "IS NOT NULL"])
            inner = self.int_expr(depth + 1) if rng.random() < 0.7 else self.text_expr(depth + 1)
            return f"({inner} {word})"
        if roll < 0.48:
            word = rng.choice(["IN", "NOT IN"])
            if rng.random() < 0.7:
                items = [self.int_literal() for _ in range(rng.randint(1, 4))]
                if rng.random() < 0.3:
                    items.append(self.int_column())
                return f"({self.int_expr(depth + 1)} {word} ({', '.join(items)}))"
            items = [self.text_literal() for _ in range(rng.randint(1, 3))]
            return f"({self.text_expr(depth + 1)} {word} ({', '.join(items)}))"
        if roll < 0.54:
            word = rng.choice(["BETWEEN", "NOT BETWEEN"])
            return (f"({self.int_expr(depth + 1)} {word} {self.int_expr(2)} AND "
                    f"{self.int_expr(2)})")
        if roll < 0.57:
            word = rng.choice(["IS", "IS NOT"])
            return f"({self.int_expr(depth + 1)} {word} {self.int_expr(depth + 1)})"
        if roll < 0.6:
            return self.int_column()
        if roll < 0.72:
            return f"(NOT {self.predicate(depth + 1)})"
        if roll < 0.86:
            return f"({self.predicate(depth + 1)} AND {self.predicate(depth + 1)})"
        return f"({self.predicate(depth + 1)} OR {self.predicate(depth + 1)})"

    # -- FROM

    def from_clause(self) -> str:
        rng = self.rng
        parts = [f"{rng.choice(TABLES)} a"]
        self.aliases = ["a"]
        for alias in ("b", "c")[: rng.choice([0, 1, 1, 1, 2, 2])]:
            table = rng.choice(TABLES)
            kind = rng.choices(["JOIN", "LEFT JOIN", "CROSS JOIN"], [4, 6, 1])[0]
            if kind == "CROSS JOIN":
                parts.append(f"CROSS JOIN {table} {alias}")
                self.aliases.append(alias)
                continue
            previous = rng.choice(self.aliases)
            self.aliases.append(alias)
            roll = rng.random()
            if roll < 0.55:
                column = rng.choice(["k", "k", "v", "id"])
                on = f"{previous}.{column} = {alias}.{column}"
            elif roll < 0.7:
                on = f"{previous}.k = {alias}.k AND {previous}.s = {alias}.s"
            elif roll < 0.8:
                on = f"{previous}.v < {alias}.v"
            else:
                on = f"{previous}.k = {alias}.k"
            if rng.random() < 0.3:
                side = rng.choice([previous, alias])
                saved = self.aliases
                self.aliases = [side]
                on += f" AND {self.predicate(1)}"
                self.aliases = saved
            parts.append(f"{kind} {table} {alias} ON {on}")
        return " ".join(parts)

    # -- whole queries

    def query(self) -> Query:
        rng = self.rng
        source = self.from_clause()
        where = f" WHERE {self.predicate()}" if rng.random() < 0.8 else ""
        roll = rng.random()
        group = having = ""
        if roll < 0.6:
            outputs = []
            for _ in range(rng.randint(1, 3)):
                pick = rng.random()
                if pick < 0.45:
                    outputs.append(self.int_expr())
                elif pick < 0.7:
                    outputs.append(self.text_expr())
                else:
                    outputs.append(self.predicate(1))
            distinct = "DISTINCT " if rng.random() < 0.2 else ""
        else:
            keys = []
            if roll < 0.9:
                for _ in range(rng.randint(1, 2)):
                    key = self.int_expr(1) if rng.random() < 0.6 else self.text_expr(1)
                    if "." not in key:  # a bare number would mean a position
                        key = self.int_column()
                    keys.append(key)
                group = " GROUP BY " + ", ".join(keys)
            outputs = list(keys)
            for _ in range(rng.randint(1, 3)):
                outputs.append(self.aggregate())
            if rng.random() < 0.3:
                having = f" HAVING {self.having()}"
            distinct = ""
        order = ""
        positions: list[int] = []
        total = False
        if rng.random() < 0.5:
            count = len(outputs)
            positions = rng.sample(range(count), rng.randint(1, count))
            total = len(positions) == count
            terms = []
            for position in positions:
                term = str(position + 1)
                term += rng.choice(["", " ASC", " DESC"])
                term += rng.choice(["", "", " NULLS FIRST", " NULLS LAST"])
                terms.append(term)
            order = " ORDER BY " + ", ".join(terms)
            if total and rng.random() < 0.5:
                order += f" LIMIT {rng.randint(0, 5)}"
                if rng.random() < 0.5:
                    order += f" OFFSET {rng.randint(0, 3)}"
        columns = ", ".join(outputs)
        sql = f"SELECT {distinct}{columns} FROM {source}{where}{group}{having}{order}"
        return Query(sql, positions, total)

    def aggregate(self) -> str:
        rng = self.rng
        name = rng.choice(["COUNT(*)", "COUNT", "COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL"])
        if name == "COUNT(*)":
            return name
        if name in ("MIN", "MAX", "COUNT") and rng.random() < 0.3:
            argument = self.text_expr(1)
        else:
            argument = self.int_expr(1)
        distinct = "DISTINCT " if name in ("COUNT", "SUM") and rng.random() < 0.25 else ""
        return f"{name}({distinct}{argument})"

    def having(self) -> str:
        rng = self.rng
        left = rng.choice(["COUNT(*)", f"SUM({self.int_column()})", f"MAX({self.int_column()})",
                           f"COUNT({self.int_column()})"])
        op = rng.choice([">", "<=", "=", "<>"])
        condition = f"({left} {op} {rng.randint(0, 4)})"
        if rng.random() < 0.3:
            condition = f"(NOT {condition})"
        return condition
