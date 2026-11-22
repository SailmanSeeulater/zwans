from sheetcalc import DIV0, PARSE, VALUE, Error, Sheet


def test_numbers_text_and_blanks() -> None:
    sheet = Sheet()
    sheet.set("a1", " 4 ")
    sheet.set("A2", "hello")

    assert sheet.get("A1") == 4.0
    assert sheet.get("A2") == "hello"
    assert sheet.get("A3") is None
    assert sheet.text("A1") == "4"


def test_a_formula_follows_the_cells_it_uses() -> None:
    sheet = Sheet()
    sheet.set("A1", "4")
    sheet.set("A2", "=A1*2")
    sheet.set("A3", "=SUM(A1:A2)")

    assert sheet.get("A3") == 12.0
    sheet.set("A1", "10")
    assert sheet.get("A2") == 20.0
    assert sheet.get("A3") == 30.0


def test_functions_and_comparisons() -> None:
    sheet = Sheet()
    sheet.load({"A1": "3", "A2": "text", "A3": "8", "B1": "=MAX(A1:A3, 5)"})
    sheet.set("B2", "=COUNT(A1:A3)")
    sheet.set("B3", "=IF(A1 < A3, -A1, A3)")

    assert sheet.get("B1") == 8.0
    assert sheet.get("B2") == 2.0
    assert sheet.get("B3") == -3.0


def test_errors() -> None:
    sheet = Sheet()
    sheet.load({"A1": "1", "A2": "0", "A3": "word"})
    sheet.set("B1", "=A1/A2")
    sheet.set("B2", "=A3+1")
    sheet.set("B3", "=SUM(")
    sheet.set("B4", "=IF(A1, 7, B1)")

    assert sheet.get("B1") == DIV0 and isinstance(sheet.get("B1"), Error)
    assert sheet.get("B2") == VALUE
    assert sheet.get("B3") == PARSE
    assert sheet.get("B4") == 7.0


def test_clearing_a_cell() -> None:
    sheet = Sheet()
    sheet.set("A1", "5")
    sheet.set("A2", "=A1+1")
    sheet.set("A1", "")

    assert sheet.get("A1") is None
    assert sheet.get("A2") == 1.0


def test_an_edit_evaluates_only_what_depends_on_it() -> None:
    sheet = Sheet()
    sheet.load({"A1": "1", "B1": "2"})
    sheet.set("A2", "=A1+1")
    sheet.set("B2", "=B1+1")
    before = sheet.stats.evaluations

    sheet.set("A1", "5")

    assert sheet.stats.evaluations - before == 1
    assert sheet.get("A2") == 6.0
