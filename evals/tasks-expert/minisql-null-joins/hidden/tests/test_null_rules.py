"""The README's NULL rules one at a time, and its rule on where conditions are checked."""

import random
import sqlite3

import pytest

from minisql import Database

SETUP = """
CREATE TABLE a (id INTEGER, k INTEGER, v INTEGER, s TEXT);
CREATE TABLE b (id INTEGER, k INTEGER, v INTEGER, s TEXT);
INSERT INTO a VALUES (1, 1, 5, 'x'), (2, 2, NULL, 'y'), (3, NULL, 7, NULL), (4, 4, 1, 'x'),
                     (5, NULL, NULL, 'z');
INSERT INTO b VALUES (10, 1, 3, 'p'), (11, 1, NULL, 'q'), (12, NULL, 8, 'p'),
                     (13, 2, 6, NULL), (14, NULL, NULL, NULL);
"""


@pytest.fixture
def db() -> Database:
    database = Database()
    database.execute(SETUP)
    return database


def rows(db: Database, sql: str) -> list[tuple]:
    return sorted(db.execute(sql), key=repr)


# -- three-valued logic


def test_logic_has_three_values(db: Database) -> None:
    assert db.execute(
        "SELECT NULL AND 1, NULL AND 0, NULL OR 1, NULL OR 0, NOT NULL, NOT (NULL = NULL)"
    ) == [(None, 0, 1, None, None, None)]


def test_not_of_an_unknown_comparison_keeps_nothing(db: Database) -> None:
    assert rows(db, "SELECT id FROM a WHERE NOT (v > 4)") == [(4,)]
    assert rows(db, "SELECT id FROM a WHERE NOT (v > 4 OR s = 'z')") == [(4,)]


def test_not_in_with_a_null_in_the_list(db: Database) -> None:
    assert rows(db, "SELECT id FROM a WHERE k NOT IN (1, NULL)") == []
    assert rows(db, "SELECT id FROM a WHERE k NOT IN (1, 2)") == [(4,)]
    assert db.execute("SELECT 3 NOT IN (1, NULL), 1 IN (1, NULL), NULL IN (1), 2 IN (1, 3)") == [
        (None, 1, None, 0)
    ]


def test_between_with_null(db: Database) -> None:
    assert db.execute("SELECT NULL BETWEEN 1 AND 2, 5 NOT BETWEEN 1 AND NULL, "
                      "0 NOT BETWEEN 1 AND NULL") == [(None, None, 1)]
    assert rows(db, "SELECT id FROM a WHERE v NOT BETWEEN 2 AND 6") == [(3,), (4,)]


def test_delete_and_update_skip_unknown_rows(db: Database) -> None:
    db.execute("UPDATE a SET s = 'w' WHERE NOT (v < 6)")
    assert rows(db, "SELECT id FROM a WHERE s = 'w'") == [(3,)]
    db.execute("DELETE FROM a WHERE NOT (k IN (1, 2))")
    assert rows(db, "SELECT id FROM a") == [(1,), (2,), (3,), (5,)]


# -- joins


def test_null_join_keys_match_nothing(db: Database) -> None:
    assert rows(db, "SELECT a.id, b.id FROM a JOIN b ON a.k = b.k") == [
        (1, 10), (1, 11), (2, 13),
    ]
    assert rows(db, "SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k") == [
        (1, 10), (1, 11), (2, 13), (3, None), (4, None), (5, None),
    ]


def test_left_join_then_where_is_null_finds_the_unmatched_rows(db: Database) -> None:
    assert rows(db, "SELECT a.id FROM a LEFT JOIN b ON a.k = b.k WHERE b.id IS NULL") == [
        (3,), (4,), (5,),
    ]
    assert rows(db, "SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k "
                    "WHERE COALESCE(b.v, 0) = 0") == [(1, 11), (3, None), (4, None), (5, None)]
    assert rows(db, "SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k "
                    "WHERE b.v > 4 OR a.id = 4") == [(2, 13), (4, None)]


def test_a_condition_in_on_keeps_every_left_row(db: Database) -> None:
    assert rows(db, "SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k AND b.v > 4") == [
        (1, None), (2, 13), (3, None), (4, None), (5, None),
    ]
    assert rows(db, "SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k AND a.s = 'y'") == [
        (1, None), (2, 13), (3, None), (4, None), (5, None),
    ]


# -- grouping, aggregates, ordering


def test_aggregates_skip_nulls(db: Database) -> None:
    assert db.execute(
        "SELECT COUNT(*), COUNT(v), COUNT(DISTINCT s), SUM(v), AVG(v), MIN(v), MAX(v), "
        "TOTAL(v) FROM a"
    ) == [(5, 3, 3, 13, 13 / 3, 1, 7, 13.0)]
    assert db.execute(
        "SELECT COUNT(*), COUNT(v), SUM(v), AVG(v), MIN(v), MAX(v), TOTAL(v) FROM a "
        "WHERE v IS NULL"
    ) == [(2, 0, None, None, None, None, 0.0)]


def test_group_by_puts_nulls_in_one_group(db: Database) -> None:
    assert rows(db, "SELECT k, COUNT(*), COUNT(k), SUM(v) FROM a GROUP BY k") == [
        (1, 1, 1, 5), (2, 1, 1, None), (4, 1, 1, 1), (None, 2, 0, 7),
    ]
    assert rows(db, "SELECT DISTINCT k FROM b") == [(1,), (2,), (None,)]
    assert rows(db, "SELECT DISTINCT b.s, a.s FROM a LEFT JOIN b ON a.k = b.k") == [
        ("p", "x"), ("q", "x"), (None, "x"), (None, "y"), (None, "z"), (None, None),
    ]


def test_order_by_puts_nulls_first_ascending_and_last_descending(db: Database) -> None:
    assert db.execute("SELECT v FROM a ORDER BY v") == [(None,), (None,), (1,), (5,), (7,)]
    assert db.execute("SELECT v FROM a ORDER BY v DESC") == [(7,), (5,), (1,), (None,), (None,)]
    assert db.execute("SELECT v FROM a ORDER BY v NULLS LAST") == [
        (1,), (5,), (7,), (None,), (None,),
    ]
    assert db.execute("SELECT v FROM a ORDER BY v DESC NULLS FIRST") == [
        (None,), (None,), (7,), (5,), (1,),
    ]
    assert db.execute("SELECT k, id FROM a ORDER BY k DESC, id DESC") == [
        (4, 4), (2, 2), (1, 1), (None, 5), (None, 3),
    ]


# -- where conditions are checked


def big_tables(seed: int) -> tuple[Database, sqlite3.Connection]:
    rng = random.Random(seed)
    db = Database()
    lite = sqlite3.connect(":memory:")
    statements = ["CREATE TABLE a (id INTEGER, k INTEGER, v INTEGER, s TEXT)",
                  "CREATE TABLE b (id INTEGER, k INTEGER, v INTEGER, s TEXT)"]
    for table in ("a", "b"):
        values = []
        for number in range(300):
            k = "NULL" if rng.random() < 0.2 else str(rng.randint(0, 40))
            v = "NULL" if rng.random() < 0.2 else str(rng.randint(0, 9))
            s = "NULL" if rng.random() < 0.2 else f"'{rng.choice('xyz')}'"
            values.append(f"({number}, {k}, {v}, {s})")
        statements.append(f"INSERT INTO {table} VALUES {', '.join(values)}")
    for statement in statements:
        db.execute(statement)
        lite.execute(statement)
    return db, lite


def count(lite: sqlite3.Connection, table: str, condition: str) -> int:
    return lite.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition}").fetchone()[0]


CASES = [
    # (join, WHERE, condition on a alone, condition on b alone)
    ("JOIN", "a.v > 5 AND b.s = 'x'", "a.v > 5", "b.s = 'x'"),
    ("JOIN", "b.v < 3 AND a.k + 1 > 10", "a.k + 1 > 10", "b.v < 3"),
    ("JOIN", "(a.s = 'y' OR a.v = 1) AND b.v IN (2, 4)", "(a.s = 'y' OR a.v = 1)",
     "b.v IN (2, 4)"),
    ("LEFT JOIN", "a.v > 6", "a.v > 6", "1"),
    ("LEFT JOIN", "b.v > 6", "1", "b.v > 6"),
    ("LEFT JOIN", "a.s = 'z' AND b.s = 'x'", "a.s = 'z'", "b.s = 'x'"),
    ("LEFT JOIN", "b.v IN (1, 2) AND a.v < 5", "a.v < 5", "b.v IN (1, 2)"),
    ("LEFT JOIN", "b.v BETWEEN 2 AND 3", "1", "b.v BETWEEN 2 AND 3"),
    ("LEFT JOIN", "b.s IS NOT NULL AND a.v = 2", "a.v = 2", "b.s IS NOT NULL"),
    ("LEFT JOIN", "3 >= b.v", "1", "3 >= b.v"),
    ("LEFT JOIN", "b.k <> 7 AND b.v = 4", "1", "b.k <> 7 AND b.v = 4"),
]


@pytest.mark.parametrize(("join", "where", "on_a", "on_b"), CASES)
def test_joins_only_read_the_rows_that_pass_single_table_conditions(
    join: str, where: str, on_a: str, on_b: str
) -> None:
    db, lite = big_tables(7)
    sql = f"SELECT a.id, b.id, b.v FROM a {join} b ON a.k = b.k WHERE {where}"
    db.stats.reset()

    got = db.execute(sql)

    assert sorted(got, key=repr) == sorted(lite.execute(sql).fetchall(), key=repr), sql
    allowed = count(lite, "a", on_a) + count(lite, "b", on_b)
    assert db.stats.join_reads <= allowed, (
        f"{sql}: the join read {db.stats.join_reads} rows; only {allowed} pass the "
        "single-table conditions"
    )


@pytest.mark.parametrize(
    "where",
    ["b.v IS NULL", "COALESCE(b.v, 0) = 0", "b.v > 6 OR a.id < 5", "NOT (b.v IS NOT NULL)",
     "IFNULL(b.s, 'x') = 'x' AND a.v > 2", "CASE WHEN b.v > 3 THEN 0 ELSE 1 END"],
)
def test_a_where_clause_that_padded_rows_can_pass_keeps_the_left_join(where: str) -> None:
    db, lite = big_tables(8)
    sql = f"SELECT a.id, b.id FROM a LEFT JOIN b ON a.k = b.k WHERE {where}"

    assert sorted(db.execute(sql), key=repr) == sorted(lite.execute(sql).fetchall(), key=repr)
