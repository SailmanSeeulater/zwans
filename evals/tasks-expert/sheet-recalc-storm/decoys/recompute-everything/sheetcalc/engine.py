"""A tempting wrong answer: always right values, by working the whole sheet out again after
every edit. It breaks the README's "What an edit costs"."""

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
    evaluations: int = 0


class Sheet:
    def __init__(self) -> None:
        self._text: dict[str, str] = {}
        self._values: dict[str, Value] = {}
        self.stats = Stats()

    def set(self, cell: str, text: str) -> None:
        cell = normalize(cell)
        text = text.strip()
        if text:
            self._text[cell] = text
        else:
            self._text.pop(cell, None)
        self._rebuild()

    def load(self, cells: dict[str, str]) -> None:
        for cell, text in cells.items():
            self.set(cell, text)

    def get(self, cell: str) -> Value:
        return self._values.get(normalize(cell))

    def text(self, cell: str) -> str:
        return self._text.get(normalize(cell), "")

    def _rebuild(self) -> None:
        values: dict[str, Value] = {}
        formulas: dict[str, Node] = {}
        for cell, text in self._text.items():
            if not text.startswith("="):
                values[cell] = literal(text)
                continue
            try:
                formulas[cell] = parse(text[1:])
            except FormulaError:
                values[cell] = PARSE
        precedents = {cell: references(formula) for cell, formula in formulas.items()}
        dependents: dict[str, list[str]] = {}
        for cell, refs in precedents.items():
            for ref in refs:
                dependents.setdefault(ref, []).append(cell)
        waiting = {cell: sum(1 for r in refs if r in formulas) for cell, refs in precedents.items()}
        ready = [cell for cell, count in waiting.items() if count == 0]
        while ready:
            cell = ready.pop()
            self.stats.evaluations += 1
            values[cell] = evaluate(formulas[cell], values.get)
            for dependent in dependents.get(cell, ()):
                waiting[dependent] -= 1
                if waiting[dependent] == 0:
                    ready.append(dependent)
        for cell, count in waiting.items():
            if count > 0:
                values[cell] = CYCLE
        self._values = values
