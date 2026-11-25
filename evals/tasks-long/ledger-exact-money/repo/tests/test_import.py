from pathlib import Path

import pytest

from billfold import Book, ImportProblem, StatementMismatch
from billfold.importers import CsvProfile, import_csv, import_statement, parse_statement, read_rows


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, "utf-8")
    return path


def test_default_profile(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "bank.csv",
                 'date,amount,payee,memo\n'
                 '2026-03-02,"1,234.50",ACME GmbH,salary\n'
                 '2026-03-03,(12.00),Bank,fee\n'
                 '2026-03-04,4.50-,Cafe,\n'
                 '2026-03-05,€ -20.25,Shop,\n')
    result = import_csv(book, "Checking", path)
    assert [t.amount for t in result.added] == [1234.5, -12, -4.5, -20.25]
    assert book.balance("Checking") == 1197.75


def test_debit_and_credit_columns(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "bank.csv",
                 "date,payee,debit,credit,memo\n"
                 "2026-03-02,Shop,12.50,,\n"
                 "2026-03-03,ACME,,100.00,\n")
    result = import_csv(book, "Checking", path, "debit-credit")
    assert [t.amount for t in result.added] == [-12.5, 100]


def test_european_bank_file(book: Book, tmp_path: Path) -> None:
    book.add_account("Girokonto", opened="2026-01-01")
    path = write(tmp_path, "umsaetze.csv",
                 "Buchungstag;Betrag;Empfaenger;Verwendungszweck\n"
                 "02.03.2026;-1.234,50;Moebelhaus;Sofa\n"
                 "03.03.2026;2.000,00;ACME GmbH;Gehalt\n")
    result = import_csv(book, "Girokonto", path, "eu-bank")
    assert [t.amount for t in result.added] == [-1234.5, 2000]


def test_importing_twice_adds_nothing(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    path = write(tmp_path, "bank.csv",
                 "date,amount,payee,memo\n2026-03-02,-3.50,Cafe,\n2026-03-02,-3.50,Cafe,\n")
    assert len(import_csv(book, "Checking", path).added) == 2
    again = import_csv(book, "Checking", path)
    assert again.added == [] and len(again.duplicates) == 2


def test_rules_run_on_import_and_undo_takes_it_all_back(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opened="2026-01-01")
    book.add_rule("Coffee", ["payee~cafe"], category="Food:Coffee")
    path = write(tmp_path, "bank.csv",
                 "date,amount,payee,memo\n2026-03-02,-3.50,Cafe Lotte,\n2026-03-03,-9.00,Shop,\n")
    result = import_csv(book, "Checking", path)
    assert [t.category for t in result.added] == ["Food:Coffee", None]
    book.undo()
    assert book.transactions_for("Checking") == []


def test_bad_rows_name_the_line() -> None:
    with pytest.raises(ImportProblem, match="line 3"):
        read_rows("date,amount,payee\n2026-03-02,1.00,A\n2026-03-03,abc,B\n", CsvProfile())


STATEMENT = """STATEMENT
ACCOUNT DE89 3704 0044 0532 0130 00
CURRENCY EUR
FROM 2026-03-01 TO 2026-03-31
OPENING 1.000,00
2026-03-02;-45,50;REWE Markt;Card payment
2026-03-05;2.500,00;ACME GmbH;Salary March
2026-03-07;(12,00);Bank;Account fee
CLOSING 3.442,50
"""


def test_statement_import(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="1000.00", opened="2026-01-01")
    result = import_statement(book, "Checking", write(tmp_path, "march.txt", STATEMENT))
    assert [t.amount for t in result.added] == [-45.5, 2500, -12]
    assert book.balance("Checking") == 3442.5
    again = import_statement(book, "Checking", write(tmp_path, "march.txt", STATEMENT))
    assert again.added == []


def test_statement_must_add_up(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="1000.00", opened="2026-01-01")
    bad = STATEMENT.replace("CLOSING 3.442,50", "CLOSING 3.442,00")
    with pytest.raises(StatementMismatch):
        import_statement(book, "Checking", write(tmp_path, "march.txt", bad))
    assert book.transactions_for("Checking") == []


def test_statement_opening_must_match_the_account(book: Book, tmp_path: Path) -> None:
    book.add_account("Checking", opening_balance="1000.00", opened="2026-01-01")
    book.add_transaction("Checking", "2026-02-10", "-10.00")
    with pytest.raises(StatementMismatch):
        import_statement(book, "Checking", write(tmp_path, "march.txt", STATEMENT))


def test_parse_statement() -> None:
    statement = parse_statement(STATEMENT)
    assert statement.currency == "EUR"
    assert statement.opening == 1000 and statement.closing == 3442.5
    assert [e.payee for e in statement.entries] == ["REWE Markt", "ACME GmbH", "Bank"]
