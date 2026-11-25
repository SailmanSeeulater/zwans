import io

import pytest

from minisql import Database, SQLError
from minisql.repl import Shell


@pytest.fixture
def shop() -> Database:
    db = Database()
    db.execute(
        """
        CREATE TABLE customer (id INTEGER, name TEXT, city TEXT);
        CREATE TABLE orders (id INTEGER, customer_id INTEGER, total INTEGER, status TEXT);
        INSERT INTO customer VALUES (1, 'ada', 'oslo'), (2, 'bo', 'rome'), (3, 'cy', 'oslo');
        INSERT INTO orders VALUES
            (10, 1, 30, 'paid'), (11, 1, 5, 'open'), (12, 2, 12, 'paid'), (13, 2, 40, 'paid');
        """
    )
    return db


def test_select_where_order(shop: Database) -> None:
    rows = shop.execute("SELECT name FROM customer WHERE city = 'oslo' ORDER BY name DESC")

    assert rows == [("cy",), ("ada",)]
    assert shop.columns() == ["name"]


def test_expressions_without_from() -> None:
    db = Database()

    assert db.execute("SELECT 1 + 2 * 3, 7 / 2, -7 / 2, 'a' || 'b', 5 / 0") == [
        (7, 3, -3, "ab", None)
    ]
    assert db.execute("SELECT 2 > 1, 2 < 1, 3 BETWEEN 1 AND 5, 4 IN (1, 2)") == [(1, 0, 1, 0)]
    assert db.execute("SELECT COALESCE(NULL, 4), NULLIF(3, 3), ABS(-2), UPPER('x')") == [
        (4, None, 2, "X")
    ]


def test_inner_join(shop: Database) -> None:
    rows = shop.execute(
        "SELECT c.name, o.total FROM customer c JOIN orders o ON o.customer_id = c.id "
        "WHERE o.status = 'paid' ORDER BY o.total"
    )

    assert rows == [("bo", 12), ("ada", 30), ("bo", 40)]


def test_left_join_keeps_customers_without_orders(shop: Database) -> None:
    rows = shop.execute(
        "SELECT c.name, o.id FROM customer c LEFT JOIN orders o ON o.customer_id = c.id "
        "ORDER BY c.name, o.id"
    )

    assert rows == [("ada", 10), ("ada", 11), ("bo", 12), ("bo", 13), ("cy", None)]


def test_group_by_and_having(shop: Database) -> None:
    rows = shop.execute(
        "SELECT customer_id, COUNT(*), SUM(total), MAX(total) FROM orders "
        "GROUP BY customer_id HAVING SUM(total) > 20 ORDER BY 1"
    )

    assert rows == [(1, 2, 35, 30), (2, 2, 52, 40)]


def test_aggregates_without_group_by(shop: Database) -> None:
    assert shop.execute("SELECT COUNT(*), AVG(total), MIN(status) FROM orders") == [
        (4, 21.75, "open")
    ]
    assert shop.execute("SELECT COUNT(*) FROM orders WHERE total > 100") == [(0,)]


def test_distinct_limit_offset(shop: Database) -> None:
    assert shop.execute("SELECT DISTINCT city FROM customer ORDER BY city") == [
        ("oslo",),
        ("rome",),
    ]
    assert shop.execute("SELECT id FROM orders ORDER BY id LIMIT 2 OFFSET 1") == [
        (11,),
        (12,),
    ]


def test_update_and_delete(shop: Database) -> None:
    shop.execute("UPDATE orders SET status = 'paid', total = total + 1 WHERE status = 'open'")
    assert shop.execute("SELECT total FROM orders WHERE id = 11") == [(6,)]

    shop.execute("DELETE FROM orders WHERE customer_id = 2")
    assert shop.execute("SELECT COUNT(*) FROM orders") == [(2,)]


def test_insert_with_columns_fills_the_rest_with_null() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    db.execute("INSERT INTO t (b) VALUES ('x')")

    assert db.execute("SELECT a, b FROM t") == [(None, "x")]


def test_errors() -> None:
    db = Database()
    db.execute("CREATE TABLE t (a INTEGER)")
    for sql in (
        "SELECT b FROM t",
        "SELECT * FROM nope",
        "INSERT INTO t VALUES ('text')",
        "SELECT a FROM t GROUP BY 'x' || a",
        "SELECT FROM t",
    ):
        with pytest.raises(SQLError):
            db.execute(sql)


def test_join_filters_each_table_before_joining(shop: Database) -> None:
    shop.stats.reset()
    shop.execute(
        "SELECT c.name FROM customer c JOIN orders o ON o.customer_id = c.id "
        "WHERE c.city = 'rome' AND o.total > 20"
    )

    assert shop.stats.join_reads == 3  # one customer, two orders


def test_explain(shop: Database) -> None:
    plan = [line for (line,) in shop.execute(
        "EXPLAIN SELECT c.name FROM customer c JOIN orders o ON o.customer_id = c.id "
        "WHERE c.city = 'rome'"
    )]

    assert plan[0].startswith("PROJECT")
    assert any("JOIN (hash)" in line for line in plan)
    assert any("FILTER (c.city = 'rome')" in line for line in plan)


def test_shell() -> None:
    out = io.StringIO()
    shell = Shell(out)
    for line in [
        "CREATE TABLE t (a INTEGER, b TEXT);",
        "INSERT INTO t VALUES (1, 'x'),",
        "  (22, 'y');",
        ".mode list",
        "SELECT a, b FROM t ORDER BY a;",
        ".tables",
        "SELECT nope FROM t;",
    ]:
        assert shell.feed(line)

    assert out.getvalue() == (
        "(2 rows)\n"
        "a|b\n"
        "1|x\n"
        "22|y\n"
        "t\n"
        "Error: no such column: nope\n"
    )
    assert not shell.feed(".quit")


def test_shell_box_mode() -> None:
    out = io.StringIO()
    shell = Shell(out)
    shell.feed("SELECT 1 AS n, 'abc' AS word;")

    assert out.getvalue().splitlines() == [
        "+---+------+",
        "| n | word |",
        "+---+------+",
        "| 1 | abc  |",
        "+---+------+",
    ]
