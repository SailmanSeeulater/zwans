"""A tempting wrong answer: incremental and right on small sheets, but it walks the sheet by
recursion, so a deep column of formulas overflows the stack."""

from __future__ import annotations

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
        self._precedents: dict[str, set[str]] = {}  # formula cell -> the cells it references
        self._dependents: dict[str, set[str]] = {}  # cell -> the formula cells referencing it
        self._cyclic: set[str] = set()  # cells whose value is #CYCLE!
        self.stats = Stats()

    def set(self, cell: str, text: str) -> None:
        """Put `text` in a cell: a formula if it starts with "=", else a number or text.
        "" clears the cell."""
        cell = normalize(cell)
        text = text.strip()
        # The cell's old formula no longer makes it anyone's dependent.
        for reference in self._precedents.pop(cell, ()):
            self._dependents[reference].discard(cell)
        self._formulas.pop(cell, None)
        self._values.pop(cell, None)
        if not text:
            self._text.pop(cell, None)
        elif text.startswith("="):
            self._text[cell] = text
            try:
                formula = parse(text[1:])
            except FormulaError:
                self._values[cell] = PARSE
            else:
                self._formulas[cell] = formula
                # Every reference counts, to blank cells too: they may be filled in later.
                self._precedents[cell] = references(formula)
                for reference in self._precedents[cell]:
                    self._dependents.setdefault(reference, set()).add(cell)
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

    def _recalculate(self, edited: str) -> None:
        """Bring the edited cell and everything that depends on it up to date, each cell
        once, precedents first: a depth-first walk gives the order."""
        affected: set[str] = set()
        self._collect(edited, affected)
        order: list[str] = []
        state: dict[str, str] = {}
        cyclic: set[str] = set()
        for cell in sorted(affected):
            self._visit(cell, affected, state, order, cyclic)
        for cell in order:
            if cell in cyclic:
                self._cyclic.add(cell)
                self._values[cell] = CYCLE
            else:
                self._settle(cell)

    def _collect(self, cell: str, affected: set[str]) -> None:
        affected.add(cell)
        for dependent in self._dependents.get(cell, ()):
            if dependent not in affected:
                self._collect(dependent, affected)

    def _visit(
        self, cell: str, affected: set[str], state: dict[str, str], order: list[str], cyclic: set[str]
    ) -> None:
        if state.get(cell) == "done":
            return
        state[cell] = "open"
        for precedent in sorted(self._precedents.get(cell, ())):
            if precedent not in affected:
                continue
            if state.get(precedent) == "open":
                cyclic.add(cell)  # a reference back up the walk: a cycle
                continue
            self._visit(precedent, affected, state, order, cyclic)
            if precedent in cyclic:
                cyclic.add(cell)
        state[cell] = "done"
        order.append(cell)

    def _settle(self, cell: str) -> None:
        formula = self._formulas.get(cell)
        if formula is None:  # a number, text, a blank or #PARSE!: set() gave it its value
            self._cyclic.discard(cell)
        elif any(p in self._cyclic for p in self._precedents[cell]):
            # It references a cyclic cell that this edit didn't touch.
            self._cyclic.add(cell)
            self._values[cell] = CYCLE
        else:
            self._cyclic.discard(cell)
            self.stats.evaluations += 1
            self._values[cell] = evaluate(formula, self._values.get)
