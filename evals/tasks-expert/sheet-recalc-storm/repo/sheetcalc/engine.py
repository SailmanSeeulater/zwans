"""The sheet: cells, their values, and keeping the values up to date."""

from collections import defaultdict
from dataclasses import dataclass

from sheetcalc.formulas import (
    CYCLE,
    PARSE,
    FormulaError,
    Node,
    Value,
    evaluate,
    literal,
    normalize,
    parse,
    references,
)


@dataclass
class Stats:
    evaluations: int = 0  # how many times a formula has been evaluated


class Sheet:
    def __init__(self) -> None:
        self._text: dict[str, str] = {}
        self._formulas: dict[str, Node] = {}
        self._values: dict[str, Value] = {}
        # cell -> the formula cells that reference it
        self._dependents: dict[str, set[str]] = defaultdict(set)
        self.stats = Stats()

    def set(self, cell: str, text: str) -> None:
        """Put `text` in a cell: a formula if it starts with "=", else a number or text.
        "" clears the cell."""
        cell = normalize(cell)
        text = text.strip()
        self._formulas.pop(cell, None)
        if not text:
            self._text.pop(cell, None)
            self._values.pop(cell, None)
        elif text.startswith("="):
            self._text[cell] = text
            try:
                formula = parse(text[1:])
            except FormulaError:
                self._values[cell] = PARSE
            else:
                self._formulas[cell] = formula
                for reference in references(formula):
                    if reference in self._text:
                        self._dependents[reference].add(cell)
        else:
            self._text[cell] = text
            self._values[cell] = literal(text)
        self._recalculate(cell)

    def load(self, cells: dict[str, str]) -> None:
        """Set many cells at once."""
        for cell, text in cells.items():
            self.set(cell, text)

    def get(self, cell: str) -> Value:
        """The cell's value: a float, text, an Error, or None when it's blank."""
        return self._values.get(normalize(cell))

    def text(self, cell: str) -> str:
        """What was typed into the cell ("" when it's blank)."""
        return self._text.get(normalize(cell), "")

    def _recalculate(self, cell: str) -> None:
        formula = self._formulas.get(cell)
        if formula is not None:
            if cell in references(formula):
                self._values[cell] = CYCLE
            else:
                self.stats.evaluations += 1
                self._values[cell] = evaluate(formula, self._values.get)
        for dependent in sorted(self._dependents[cell]):
            self._recalculate(dependent)
