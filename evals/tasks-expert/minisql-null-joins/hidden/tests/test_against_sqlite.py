"""Random tables with NULLs and random queries within the README's grammar, run by minisql
and by SQLite (the README promises the same rows), compared as multisets, and in order for
the ORDER BY terms."""

import random
import sqlite3

import pytest
import sqlgen

from minisql import Database


def normal(rows) -> list[tuple]:
    return [tuple(round(v, 6) if isinstance(v, float) else v for v in row) for row in rows]


def order_key(row: tuple) -> tuple:
    return tuple((0, 0) if v is None else (2, v) if isinstance(v, str) else (1, v) for v in row)


def both(seed: int) -> tuple[Database, sqlite3.Connection, random.Random]:
    rng = random.Random(seed)
    db = Database()
    lite = sqlite3.connect(":memory:")
    for statement in sqlgen.setup_script(rng):
        db.execute(statement)
        lite.execute(statement)
    return db, lite, rng


def check_query(db: Database, lite: sqlite3.Connection, query: sqlgen.Query, where: str) -> None:
    want = normal(lite.execute(query.sql).fetchall())
    got = normal(db.execute(query.sql))
    message = f"{where}\n{query.sql}\nminisql: {got}\nSQLite:  {want}"
    assert sorted(got, key=order_key) == sorted(want, key=order_key), message
    if query.order_positions:
        keys = [tuple(row[p] for p in query.order_positions) for row in got]
        assert keys == [tuple(row[p] for p in query.order_positions) for row in want], message


@pytest.mark.parametrize("seed", range(150))
def test_random_queries_give_the_rows_sqlite_gives(seed: int) -> None:
    db, lite, rng = both(seed)
    maker = sqlgen.QueryMaker(rng)
    for number in range(20):
        check_query(db, lite, maker.query(), f"seed {seed}, query {number}")


@pytest.mark.parametrize("seed", range(40))
def test_random_updates_and_deletes_touch_the_rows_sqlite_touches(seed: int) -> None:
    db, lite, rng = both(1000 + seed)
    maker = sqlgen.QueryMaker(rng)
    for number in range(8):
        table = rng.choice(sqlgen.TABLES)
        maker.aliases = [table]
        condition = maker.predicate()
        if rng.random() < 0.5:
            sql = f"DELETE FROM {table} WHERE {condition}"
        else:
            sql = f"UPDATE {table} SET v = {maker.int_expr(1)} WHERE {condition}"
        db.execute(sql)
        lite.execute(sql)
        for name in sqlgen.TABLES:
            query = sqlgen.Query(f"SELECT * FROM {name}", [], False)
            check_query(db, lite, query, f"seed {seed}, after statement {number}: {sql}")
