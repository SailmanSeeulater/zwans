"""Importers read amounts exactly, check statements exactly, and refuse extra places."""

from decimal import Decimal
from pathlib import Path

import pytest
from conftest import exact

from billfold import Book, ImportProblem, StatementMismatch
from billfold.importers import CsvProfile, import_csv, import_statement, parse_statement, read_rows


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, "utf-8")
    return path


def test_read_rows_gives_decimals() -> None:
    rows = read_rows('date,amount,payee\n2026-03-02,"1,234.50",A\n2026-03-03,(0.10),B\n'
                     "2026-03-04,0.20-,C\n2026-03-05,€ 19.99,D\n", CsvProfile())
    assert [r.amount for r in rows] == [Decimal("1234.50"), Decimal("-0.10"),
                                        Decimal("-0.20"), Decimal("19.99")]
    assert all(isinstance(r.amount, Decimal) for r in rows)


def test_debit_credit_and_decimal_comma_imports_are_exact(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "dc.csv", "date,payee,debit,credit\n2026-03-02,A,0.10,\n"
                                     "2026-03-03,B,,0.20\n2026-03-04,C,0.30,0.10\n")
    added = import_csv(book, "Checking", path, "debit-credit").added
    assert [str(t.amount) for t in added] == ["-0.10", "0.20", "-0.20"]
    path = write(tmp_path, "eu.csv", "Buchungstag;Betrag;Empfaenger;Verwendungszweck\n"
                                     "02.03.2026;-1.234,56;X;\n05.03.2026;0,10;Y;\n")
    added = import_csv(book, "Checking", path, "eu-bank").added
    assert [str(t.amount) for t in added] == ["-1234.56", "0.10"]
    exact(book.balance("Checking"), "-1234.56")


def test_csv_import_is_exact(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "bank.csv",
                 'date,amount,payee,memo\n'
                 '2026-03-02,(0.10),Kiosk,\n2026-03-02,0.20-,Kiosk,\n'
                 '2026-03-03,"1,234.56",ACME,\n')
    result = import_csv(book, "Checking", path)
    assert [str(t.amount) for t in result.added] == ["-0.10", "-0.20", "1234.56"]
    exact(book.balance("Checking"), "1234.26")
    again = import_csv(book, "Checking", path)
    assert again.added == [] and len(again.duplicates) == 3


def test_csv_import_refuses_extra_places(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "bank.csv",
                 "date,amount,payee,memo\n2026-03-02,-1.00,A,\n2026-03-03,-0.125,B,\n")
    with pytest.raises(ImportProblem, match="line 3"):
        import_csv(book, "Checking", path)
    assert book.transactions_for("Checking") == []


def test_csv_import_into_yen_refuses_decimals(book: Book, tmp_path: Path) -> None:
    book.add_account("Yen", currency="JPY", opened="2026-01-01")
    path = write(tmp_path, "bank.csv", "date,amount,payee,memo\n2026-03-02,\"-1,200\",A,\n"
                                       "2026-03-03,-0.5,B,\n")
    with pytest.raises(ImportProblem, match="line 3"):
        import_csv(book, "Yen", path)
    path = write(tmp_path, "bank.csv", "date,amount,payee,memo\n2026-03-02,\"-1,200\",A,\n")
    assert [str(t.amount) for t in import_csv(book, "Yen", path).added] == ["-1200"]


PENNY_STATEMENT = """STATEMENT
ACCOUNT DE89 3704 0044 0532 0130 00
CURRENCY EUR
FROM 2026-03-01 TO 2026-03-31
OPENING 0,70
2026-03-02;-0,10;Kiosk;
2026-03-02;(0,20);Kiosk;
2026-03-03;1.234,56;ACME GmbH;Salary
2026-03-04;-19,99;Streamly;
CLOSING 1.214,97
"""


def test_statement_amounts_are_exact() -> None:
    statement = parse_statement(PENNY_STATEMENT)
    exact(statement.opening, "0.70")
    exact(statement.closing, "1214.97")
    assert [str(e.amount) for e in statement.entries] == ["-0.10", "-0.20", "1234.56", "-19.99"]
    assert all(isinstance(e.amount, Decimal) for e in statement.entries)


def test_statement_import_is_exact(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="0.70", opened="2026-01-01")
    result = import_statement(book, "Checking", write(tmp_path, "march.txt", PENNY_STATEMENT))
    assert [str(t.amount) for t in result.added] == ["-0.10", "-0.20", "1234.56", "-19.99"]
    exact(book.balance("Checking"), "1214.97")


def test_statement_check_has_no_tolerance(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="0.70", opened="2026-01-01")
    bad = PENNY_STATEMENT.replace("CLOSING 1.214,97", "CLOSING 1.214,98")
    with pytest.raises(StatementMismatch):
        import_statement(book, "Checking", write(tmp_path, "march.txt", bad))
    assert book.transactions_for("Checking") == []


def test_statement_with_extra_places_names_the_line(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="0.70", opened="2026-01-01")
    bad = PENNY_STATEMENT.replace("2026-03-02;(0,20);Kiosk;", "2026-03-02;(0,205);Kiosk;")
    with pytest.raises(ImportProblem, match="line 7"):
        import_statement(book, "Checking", write(tmp_path, "march.txt", bad))
    assert book.transactions_for("Checking") == []


def test_statement_opening_is_compared_exactly(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="0.30", opened="2026-01-01")
    book.add_transaction("Checking", "2026-02-10", "0.10")
    book.add_transaction("Checking", "2026-02-11", "0.20")
    book.add_transaction("Checking", "2026-02-12", "0.10")
    result = import_statement(book, "Checking", write(tmp_path, "march.txt", PENNY_STATEMENT))
    assert len(result.added) == 4
    exact(book.balance("Checking"), "1214.97")
