"""A slow, obviously-right sheet for the tests to compare against: it works every value out
from scratch from the cells' text, following the README. It shares no code with the engine
under test (oracle_formulas.py is its own copy of the formula rules)."""

import math

import oracle_formulas as f


def compute(texts: dict[str, str]) -> tuple[dict[str, object], dict[str, set[str]], set[str]]:
    """Every non-blank cell's value, each formula's references, and the #CYCLE! cells."""
    values: dict[str, object] = {}
    formulas: dict[str, tuple] = {}
    for cell, text in texts.items():
        if not text.startswith("="):
            values[cell] = f.literal(text)
            continue
        try:
            formulas[cell] = f.parse(text[1:])
        except f.FormulaError:
            values[cell] = f.PARSE
    precedents = {cell: f.references(formula) for cell, formula in formulas.items()}
    dependents: dict[str, list[str]] = {}
    for cell, refs in precedents.items():
        for ref in refs:
            dependents.setdefault(ref, []).append(cell)
    waiting = {cell: sum(1 for r in refs if r in formulas) for cell, refs in precedents.items()}
    ready = [cell for cell, count in waiting.items() if count == 0]
    while ready:
        cell = ready.pop()
        values[cell] = f.evaluate(formulas[cell], values.get)
        for dependent in dependents.get(cell, ()):
            waiting[dependent] -= 1
            if waiting[dependent] == 0:
                ready.append(dependent)
    cyclic = {cell for cell, count in waiting.items() if count > 0}
    for cell in cyclic:
        values[cell] = f.CYCLE
    return values, precedents, cyclic


def budget(texts: dict[str, str], edited: str) -> int:
    """The most formulas an edit of `edited` may evaluate: its own and those of the cells
    depending on it, leaving out the ones whose value is #CYCLE!."""
    _, precedents, cyclic = compute(texts)
    dependents: dict[str, list[str]] = {}
    for cell, refs in precedents.items():
        for ref in refs:
            dependents.setdefault(ref, []).append(cell)
    affected, stack = {edited}, [edited]
    while stack:
        for dependent in dependents.get(stack.pop(), ()):
            if dependent not in affected:
                affected.add(dependent)
                stack.append(dependent)
    return sum(1 for cell in affected if cell in precedents and cell not in cyclic)


def is_error(value: object) -> bool:
    return type(value).__name__ == "Error"


def same(got: object, want: object) -> bool:
    if is_error(got) or is_error(want):
        return is_error(got) and is_error(want) and str(got) == str(want)
    if got is None or want is None:
        return got is None and want is None
    if isinstance(got, float) and isinstance(want, float):
        if math.isnan(got) or math.isnan(want):
            return math.isnan(got) and math.isnan(want)
        return got == want or math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)
    return type(got) is type(want) and got == want
