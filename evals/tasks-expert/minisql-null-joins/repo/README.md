# minisql

A small SQL engine in pure Python: tables live in memory, queries are parsed, planned and
run by a handful of operators. It's meant for teaching, test fixtures and quick scripts,
and for the SQL it accepts it gives the same rows SQLite does.

```python
from minisql import Database

db = Database()
db.execute("CREATE TABLE fruit (id INTEGER, name TEXT, price INTEGER)")
db.execute("INSERT INTO fruit VALUES (1, 'apple', 3), (2, 'pear', NULL), (3, 'fig', 7)")
db.execute("SELECT name FROM fruit WHERE price > 2 ORDER BY price DESC")
# [('fig',), ('apple',)]
db.columns()
# ['name']
```

`execute(sql)` runs every statement in `sql` (separated by `;`) and returns the rows of the
last one as a list of tuples (an empty list for anything but `SELECT` and `EXPLAIN`).
`columns()` gives the column names of the last result. Errors of any kind raise
`minisql.SQLError`.

There is also a shell: `python -m minisql [file.sql ...]` (type `.help` in it).

## Layout

| module | what it does |
| --- | --- |
| `tokenizer.py` | SQL text to tokens |
| `parser.py`, `nodes.py` | tokens to a syntax tree |
| `planner.py` | a SELECT to a tree of operators |
| `executor.py` | the operators: scans, filters, joins, grouping, sorting |
| `expr.py` | compiles expressions into Python functions of a row |
| `aggregates.py` | `COUNT`, `SUM`, `TOTAL`, `AVG`, `MIN`, `MAX` |
| `values.py` | how values order, group and print |
| `database.py` | tables, `INSERT`, `UPDATE`, `DELETE`, the `Database` object |
| `repl.py` | the shell |

## The SQL it understands

Statements:

- `CREATE TABLE [IF NOT EXISTS] t (col INTEGER, col TEXT, ...)` and `DROP TABLE [IF EXISTS] t`
- `INSERT INTO t [(col, ...)] VALUES (...), (...)`: columns left out are NULL. A value must
  be of the column's type or NULL.
- `UPDATE t SET col = expr, ... [WHERE cond]` and `DELETE FROM t [WHERE cond]`
- `SELECT [DISTINCT] items FROM t [AS] a [joins] [WHERE cond] [GROUP BY exprs]
  [HAVING cond] [ORDER BY terms] [LIMIT n [OFFSET m]]`, and `SELECT` without `FROM`
- `EXPLAIN SELECT ...` returns the plan, one line per row.

Joins: `[INNER] JOIN t b ON cond`, `LEFT [OUTER] JOIN t b ON cond`, `CROSS JOIN t b` and
`, t b`. A table may appear more than once under different aliases.

Select items are expressions with an optional `AS name`, `*` and `a.*`. `ORDER BY` terms are
expressions, output column numbers (`ORDER BY 2`) or output names, each with `ASC` or
`DESC` and optionally `NULLS FIRST` or `NULLS LAST`. `GROUP BY` takes expressions (or output
numbers and names); with `GROUP BY`, a select item must be a grouped expression, an
aggregate, or built from those.

Expressions: integer and `'text'` literals, `NULL`, `col` and `a.col`, parentheses,
`+ - * /`, unary `-`, `||` (concatenation), the comparisons `= == <> != < <= > >=`,
`IS` and `IS NOT`, `IS NULL` and `IS NOT NULL`, `[NOT] IN (list)`, `[NOT] BETWEEN x AND y`,
`AND`, `OR`, `NOT`, both forms of `CASE`, the functions `COALESCE`, `IFNULL`, `NULLIF`,
`ABS`, `LENGTH`, `UPPER`, `LOWER`, and the aggregates `COUNT(*)`, `COUNT([DISTINCT] x)`,
`SUM([DISTINCT] x)`, `TOTAL(x)`, `AVG(x)`, `MIN(x)`, `MAX(x)`. Operator precedence is
SQLite's.

## Values

Values are integers, text, or NULL; `AVG` and `TOTAL` give reals. Comparing values of
different kinds orders NULL below numbers and numbers below text; text compares by its
characters (binary order, so `'B' < 'a'`). Integer division truncates toward zero
(`-7 / 2` is `-3`) and dividing by zero gives NULL. A condition is true when its value is a
nonzero number.

## NULL

minisql follows SQLite (and the SQL standard) on NULL. NULL means "unknown", so:

**Expressions.** Arithmetic, `||`, comparisons and `ABS`, `LENGTH`, `UPPER`, `LOWER` with a
NULL operand give NULL; `NULL = NULL` is NULL, not true. `IS` and `IS NOT` never give NULL:
`a IS b` is true when both are NULL or both are equal. `COALESCE` and `IFNULL` give their
first non-NULL argument; `NULLIF(a, b)` is NULL when `a = b` is true and `a` otherwise.

**Logic has three values**: true (1), false (0) and NULL.

| `a` | `b` | `a AND b` | `a OR b` | `NOT a` |
| --- | --- | --- | --- | --- |
| true | NULL | NULL | true | false |
| false | NULL | false | NULL | true |
| NULL | NULL | NULL | NULL | NULL |

`x IN (v1, v2, ...)` is true if `x = vi` is true for some `vi`; otherwise it is NULL if `x`
is NULL or any `vi` is NULL, and false if not. `x NOT IN (...)` is `NOT (x IN (...))`, so
`3 NOT IN (1, NULL)` is NULL. `x BETWEEN a AND b` is `x >= a AND x <= b`, and
`x NOT BETWEEN a AND b` is `NOT (x BETWEEN a AND b)`.

**Conditions.** `WHERE`, `ON` and `HAVING` keep a row only when the condition is true; NULL
counts as not true. The same goes for the `WHERE` of `UPDATE` and `DELETE`, and for each
`WHEN` of a `CASE`. In `CASE x WHEN v THEN ...`, a branch is taken when `x = v` is true, so
a NULL `x` takes no `WHEN` branch.

**Joins.** An inner join gives each pair of rows for which `ON` is true. Since
`NULL = NULL` isn't true, a row whose join column is NULL joins with nothing. A `LEFT JOIN`
gives the same pairs, plus each left row that is in no pair, once, with every column of the
right table NULL (a padded row). `WHERE` then filters the result of the joins, padded rows
included. So `a LEFT JOIN b ON a.id = b.a_id WHERE b.a_id IS NULL` finds the rows of `a`
that have no match in `b`, while a condition on `b` in `ON` instead of `WHERE` keeps every
row of `a`.

**Grouping.** `GROUP BY` puts all rows whose group values are NULL in one group, and
`DISTINCT` treats NULLs as equal to each other: there is at most one NULL row per group of
otherwise equal rows.

**Aggregates** skip NULLs: `COUNT(*)` counts rows, `COUNT(x)` counts the rows where `x` is
not NULL, `COUNT(DISTINCT x)` the distinct non-NULL values. `SUM`, `AVG`, `MIN` and `MAX`
work on the non-NULL values only and are NULL when there are none; `TOTAL` is like `SUM`
but always a real and `0.0` when there are no values. A query with aggregates and no
`GROUP BY` gives exactly one row, even when no rows match.

**Ordering.** In `ORDER BY`, NULL is smaller than every other value: NULLs come first with
`ASC` (the default) and last with `DESC`. `NULLS FIRST` and `NULLS LAST` override that. Rows
that tie on every term may come in any order.

## Where conditions are checked

The planner splits `WHERE` (and the `ON` of inner joins) into its `AND`-ed parts and checks
each part as early as it can. A part that uses the columns of only one table is checked
while that table is scanned, before any join, so joins never see the rows it rejects; that
keeps joins of big tables affordable. A part that uses several tables is checked by the
join that brings in the last of them.

The right table of a `LEFT JOIN` is the exception, because rejecting its rows before the
join would produce padded rows that the query must not return; a `WHERE` part on that table
is checked after the join. But when the `WHERE` clause can never be true for a padded row,
the `LEFT JOIN` gives exactly the rows an inner join would, and minisql runs it as an inner
join, checking the right table's parts at its scan like any other. That is the case
whenever one of the `AND`-ed parts of `WHERE` compares a column of the right table with a
constant (`=`, `<>`, `<`, `<=`, `>`, `>=`, `IN (...)`, `BETWEEN ... AND ...`) or is
`col IS NOT NULL` for such a column. Parts like `b.price IS NULL`,
`COALESCE(b.price, 0) = 0` or `b.price > 10 OR a.id = 1` don't make that guarantee.

`db.stats` counts the work queries do: `rows_scanned` (rows read out of tables),
`join_reads` (rows the joins read from their inputs, both sides, each row once) and
`rows_returned`; `db.stats.reset()` zeroes them. So for

```sql
SELECT a.id, b.id FROM a JOIN b ON a.id = b.a_id WHERE a.kind = 'x' AND b.price > 10
```

the join reads at most the rows of `a` whose `kind` is `'x'` plus the rows of `b` whose
`price` is over 10, and the same holds with `LEFT JOIN` in place of `JOIN`. `EXPLAIN` shows
where each condition ended up.

## Tests

```
python -m pytest -q
```
