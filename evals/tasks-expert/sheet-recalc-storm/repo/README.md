# sheetcalc

A small spreadsheet engine: cells hold numbers, text or formulas, and the engine keeps
every formula's value up to date as cells are edited.

```python
from sheetcalc import Sheet

sheet = Sheet()
sheet.set("A1", "4")
sheet.set("A2", "=A1*2")
sheet.set("A3", "=SUM(A1:A2)")
sheet.get("A3")        # 12.0
sheet.set("A1", "10")
sheet.get("A3")        # 30.0
```

## Cells

Cells are named by a column `A`-`Z` and a row `1`-`9999`. `set(cell, text)` puts text in a
cell; surrounding spaces are dropped.

- `""` clears the cell. A blank cell's value is `None`.
- Text starting with `=` is a formula.
- Other text is a number if `float()` reads it as one, and plain text otherwise.

`load(cells)` gives the same sheet as calling `set` for each entry, whatever order the
entries are in. A formula may refer to a cell that is filled in later, or never.

## Formulas

Numbers, cell names, `+ - * /`, unary `-`, parentheses, the comparisons
`= <> < > <= >=` (which give `1` or `0`), and the functions `SUM`, `MIN`, `MAX`, `COUNT`
and `IF(condition, then, otherwise)`. `SUM`, `MIN`, `MAX` and `COUNT` take any number of
arguments, each a formula or a range such as `A1:B3`.

- As an operand, a blank cell is `0` and a text cell is `#VALUE!`.
- In a range, blank cells and text cells are left out. `MIN` and `MAX` of nothing are `0`.
- Dividing by zero is `#DIV/0!`.
- An error in an operand is the result: the first one, reading left to right.
- `IF` evaluates only the branch it takes, so an error in the other branch doesn't matter.
- Text that starts with `=` but isn't a formula has the value `#PARSE!`.

Error values are instances of `sheetcalc.Error` (a `str`): `DIV0`, `VALUE`, `PARSE`,
`CYCLE`.

## Cycles

A formula *references* every cell it mentions, including each cell of a range and both
branches of an `IF`, whether or not evaluating it reads them.

A cell is **on a cycle** when following references from it leads back to it. A cell that is
on a cycle, or that references a cell whose value is `#CYCLE!`, has the value `#CYCLE!`.
This is decided by the references alone, not by what evaluation would read: `=IF(1, 5, B1)`
is `#CYCLE!` when `B1` is. When an edit breaks the cycle, the cells get their real values
back.

## What an edit costs

Big sheets are edited one cell at a time, so an edit must not redo the whole sheet.

After `set`, the only formulas evaluated are the edited cell's and those of the cells that
depend on it, directly or through other cells, **each at most once**. That holds for the
edit and reading the sheet back afterwards taken together, so evaluating lazily, when a
value is read, is fine. Formulas that don't depend on the edited cell are not evaluated,
and neither are cells whose value is `#CYCLE!` or `#PARSE!`.

`sheet.stats.evaluations` counts every evaluation of a formula, and the tests hold the
engine to this. Sheets can be deep: a column where each cell adds to the one above it can
run to thousands of rows.

## Tests

```
python -m pytest -q
```
