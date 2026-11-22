"""The sheet: cells, their values, and keeping the values up to date."""

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
        once, precedents first. No recursion: a column of formulas can be thousands deep."""
        affected = {edited}
        stack = [edited]
        while stack:
            for dependent in self._dependents.get(stack.pop(), ()):
                if dependent not in affected:
                    affected.add(dependent)
                    stack.append(dependent)
        # Kahn's algorithm over the affected cells: a cell is ready once every affected cell
        # it references is done.
        waiting = {
            cell: sum(1 for p in self._precedents.get(cell, ()) if p in affected)
            for cell in affected
        }
        ready = [cell for cell, count in waiting.items() if count == 0]
        done = 0
        while ready:
            cell = ready.pop()
            done += 1
            self._settle(cell)
            for dependent in self._dependents.get(cell, ()):
                if dependent in affected:
                    waiting[dependent] -= 1
                    if waiting[dependent] == 0:
                        ready.append(dependent)
        if done < len(affected):
            # Never ready: on a cycle, or referencing a cell that is.
            for cell, count in waiting.items():
                if count > 0:
                    self._cyclic.add(cell)
                    self._values[cell] = CYCLE

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
