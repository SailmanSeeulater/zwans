"""The engine against the README: right values after any sequence of edits, cycles found
and recovered from, and no more work per edit than "What an edit costs" allows."""

import random

import oracle
import pytest

from sheetcalc import CYCLE, DIV0, PARSE, Error, Sheet

CELLS = [f"{column}{row}" for row in range(1, 6) for column in "ABCD"]


def cost(sheet: Sheet, cell: str, text: str, read: list[str]) -> int:
    """Formulas evaluated by one edit and reading `read` back afterwards."""
    before = sheet.stats.evaluations
    sheet.set(cell, text)
    for name in read:
        sheet.get(name)
    return sheet.stats.evaluations - before


def is_cycle(value: object) -> bool:
    return isinstance(value, Error) and value == CYCLE


# -- values


def test_a_formula_can_refer_to_a_cell_filled_in_later() -> None:
    sheet = Sheet()
    sheet.set("A1", "=B1+1")
    assert sheet.get("A1") == 1.0

    sheet.set("B1", "41")

    assert sheet.get("A1") == 42.0


def test_load_gives_the_same_sheet_in_any_order() -> None:
    cells = {"A3": "=SUM(A1:A2)", "A2": "=A1*2", "A1": "5", "B1": "=A3+C9"}
    forwards, backwards = Sheet(), Sheet()
    forwards.load(cells)
    backwards.load(dict(reversed(list(cells.items()))))

    for cell in cells:
        assert forwards.get(cell) == backwards.get(cell), cell
    assert forwards.get("B1") == 15.0


def test_a_blank_cell_in_a_range_counts_once_it_is_filled() -> None:
    sheet = Sheet()
    sheet.load({"A1": "1", "A3": "3"})
    sheet.set("B1", "=SUM(A1:A4)")
    sheet.set("B2", "=COUNT(A1:A4)")

    sheet.set("A2", "10")
    sheet.set("A4", "100")

    assert sheet.get("B1") == 114.0
    assert sheet.get("B2") == 4.0


def test_a_parse_error_goes_away_when_the_formula_is_fixed() -> None:
    sheet = Sheet()
    sheet.set("A1", "=1+")
    sheet.set("A2", "=A1+1")
    assert sheet.get("A1") == PARSE and sheet.get("A2") == PARSE

    sheet.set("A1", "=1+1")

    assert sheet.get("A2") == 3.0


def test_text_that_looks_like_an_error_is_only_text() -> None:
    sheet = Sheet()
    sheet.set("A1", "#CYCLE!")
    sheet.set("A2", "=COUNT(A1:A1)")

    assert sheet.get("A1") == "#CYCLE!" and not isinstance(sheet.get("A1"), Error)
    assert sheet.get("A2") == 0.0


# -- cycles


def test_a_cell_that_refers_to_itself() -> None:
    sheet = Sheet()
    sheet.set("A1", "=A1+1")
    sheet.set("A2", "=SUM(A1:A3)")

    assert is_cycle(sheet.get("A1"))
    assert is_cycle(sheet.get("A2"))  # A2 is in its own range


def test_a_cycle_through_several_cells_and_what_hangs_off_it() -> None:
    sheet = Sheet()
    sheet.load({"A1": "=C1+1", "B1": "=A1+1", "C1": "=B1+1", "D1": "=B1*2", "D2": "7"})

    for cell in ("A1", "B1", "C1", "D1"):
        assert is_cycle(sheet.get(cell)), cell
    assert sheet.get("D2") == 7.0


def test_breaking_a_cycle_gives_the_cells_their_values_back() -> None:
    sheet = Sheet()
    sheet.load({"A1": "=C1+1", "B1": "=A1+1", "C1": "=B1+1", "D1": "=B1*2"})

    sheet.set("C1", "10")

    assert [sheet.get(c) for c in ("A1", "B1", "C1", "D1")] == [11.0, 12.0, 10.0, 24.0]

    sheet.set("C1", "=D1")
    assert all(is_cycle(sheet.get(c)) for c in ("A1", "B1", "C1", "D1"))
    sheet.set("D1", "1")
    assert [sheet.get(c) for c in ("A1", "B1", "C1", "D1")] == [2.0, 3.0, 1.0, 1.0]


def test_a_cycle_is_decided_by_references_not_by_what_is_read() -> None:
    sheet = Sheet()
    sheet.load({"A1": "=B1", "B1": "=A1", "C1": "=IF(1, 5, A1)", "C2": "=IF(0, C2, 5)"})

    assert is_cycle(sheet.get("C1"))
    assert is_cycle(sheet.get("C2"))


def test_an_edit_elsewhere_leaves_a_cells_cycle_error_alone() -> None:
    sheet = Sheet()
    sheet.load({"A1": "=B1", "B1": "=A1", "C1": "0", "D1": "=IF(C1 > 0, 1, A1)"})
    assert is_cycle(sheet.get("D1"))

    spent = cost(sheet, "C1", "1", ["D1"])  # D1 would read only C1 now, but still names A1

    assert is_cycle(sheet.get("D1"))
    assert spent == 0

    sheet.set("B1", "3")
    assert sheet.get("D1") == 1.0


def test_division_by_a_cycle_is_a_cycle_not_a_division_error() -> None:
    sheet = Sheet()
    sheet.load({"A1": "=A1", "B1": "=1/0+A1"})

    assert is_cycle(sheet.get("B1"))
    sheet.set("A1", "2")
    assert sheet.get("B1") == DIV0


# -- what an edit costs


def test_a_formula_rewritten_to_use_another_cell_forgets_the_old_one() -> None:
    sheet = Sheet()
    sheet.load({"A1": "1", "C1": "2", "B1": "=A1+1"})
    sheet.set("B1", "=C1+1")

    assert cost(sheet, "A1", "50", ["B1"]) == 0
    assert cost(sheet, "C1", "9", ["B1"]) == 1
    assert sheet.get("B1") == 10.0


def test_a_cleared_formula_is_nobodys_dependent() -> None:
    sheet = Sheet()
    sheet.load({"A1": "1", "B1": "=A1+1"})
    sheet.set("B1", "")

    assert cost(sheet, "A1", "2", ["B1"]) == 0
    assert sheet.get("B1") is None


def test_cells_reached_by_many_paths_are_evaluated_once() -> None:
    sheet = Sheet()
    sheet.set("A1", "1")
    sheet.set("B1", "1")
    rows = 18
    for row in range(2, rows + 1):
        sheet.set(f"A{row}", f"=A{row - 1}+B{row - 1}")
        sheet.set(f"B{row}", f"=A{row - 1}+B{row - 1}")

    spent = cost(sheet, "A1", "2", [f"A{rows}", f"B{rows}"])

    assert spent <= 2 * (rows - 1)
    assert sheet.get(f"A{rows}") == 3.0 * 2 ** (rows - 2)


def test_an_edit_near_the_end_of_a_long_column_doesnt_redo_the_column() -> None:
    sheet = Sheet()
    rows = 3000
    sheet.set("A1", "1")
    for row in range(2, rows):
        sheet.set(f"A{row}", f"=A{row - 1}+1")
    sheet.set("B1", "5")
    sheet.set(f"A{rows}", f"=A{rows - 1}+B1")

    assert cost(sheet, "B1", "6", [f"A{rows}"]) == 1
    assert sheet.get(f"A{rows}") == rows - 1 + 6.0


def test_an_edit_at_the_top_of_a_deep_column_reaches_the_bottom() -> None:
    sheet = Sheet()
    rows = 5000
    sheet.set("A1", "1")
    for row in range(2, rows + 1):
        sheet.set(f"A{row}", f"=A{row - 1}+1")

    spent = cost(sheet, "A1", "100", [f"A{rows}"])

    assert sheet.get(f"A{rows}") == 100.0 + rows - 1
    assert spent <= rows - 1


def test_a_deep_cycle_is_found_without_running_out_of_stack() -> None:
    sheet = Sheet()
    rows = 3000
    sheet.set("A1", "1")
    for row in range(2, rows + 1):
        sheet.set(f"A{row}", f"=A{row - 1}+1")

    sheet.set("A1", f"=A{rows}")

    assert is_cycle(sheet.get("A1")) and is_cycle(sheet.get(f"A{rows // 2}"))
    sheet.set("A1", "0")
    assert sheet.get(f"A{rows}") == rows - 1.0


# -- any sequence of edits


def random_expression(rng: random.Random, depth: int = 0) -> str:
    roll = rng.random()
    if depth >= 2 or roll < 0.3:
        return rng.choice(CELLS) if rng.random() < 0.75 else str(rng.randint(0, 9))
    if roll < 0.55:
        op = rng.choice(["+", "-", "*", "+", "-", "/"])
        return f"({random_expression(rng, depth + 1)} {op} {random_expression(rng, depth + 1)})"
    if roll < 0.65:
        op = rng.choice(["<", ">", "=", "<>", "<=", ">="])
        return f"({random_expression(rng, depth + 1)} {op} {random_expression(rng, depth + 1)})"
    if roll < 0.7:
        return f"-{random_expression(rng, depth + 1)}"
    if roll < 0.88:
        name = rng.choice(["SUM", "MIN", "MAX", "COUNT"])
        args = []
        for _ in range(rng.randint(1, 2)):
            if rng.random() < 0.7:
                args.append(f"{rng.choice(CELLS)}:{rng.choice(CELLS)}")
            else:
                args.append(random_expression(rng, depth + 1))
        return f"{name}({', '.join(args)})"
    parts = [random_expression(rng, depth + 1) for _ in range(3)]
    return f"IF({parts[0]}, {parts[1]}, {parts[2]})"


def random_text(rng: random.Random) -> str:
    roll = rng.random()
    if roll < 0.25:
        return str(rng.randint(-5, 9))
    if roll < 0.3:
        return "word"
    if roll < 0.4:
        return ""
    if roll < 0.44:
        return rng.choice(["=SUM(", "=A1+", "=IF(A1, 2)", "=A1:B2"])
    return "=" + random_expression(rng)


@pytest.mark.parametrize("seed", range(150))
def test_any_sequence_of_edits_matches_working_it_out_from_scratch(seed: int) -> None:
    rng = random.Random(seed)
    sheet = Sheet()
    texts: dict[str, str] = {}
    for step in range(60):
        cell, text = rng.choice(CELLS), random_text(rng)
        if text:
            texts[cell] = text
        else:
            texts.pop(cell, None)
        spent = cost(sheet, cell, text, CELLS)

        want, _, _ = oracle.compute(texts)
        for name in CELLS:
            got = sheet.get(name)
            assert oracle.same(got, want.get(name)), (
                f"seed {seed}, step {step}: after setting {cell} to {text!r}, {name} is "
                f"{got!r} but should be {want.get(name)!r}. The sheet: {texts}"
            )
        allowed = oracle.budget(texts, cell)
        assert spent <= allowed, (
            f"seed {seed}, step {step}: setting {cell} to {text!r} evaluated {spent} "
            f"formulas; at most {allowed} depend on it. The sheet: {texts}"
        )
