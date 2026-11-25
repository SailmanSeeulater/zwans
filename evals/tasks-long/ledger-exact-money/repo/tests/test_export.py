import csv
import io
import json
from pathlib import Path

from billfold import Book
from billfold.exporters import csv_text, export_document, export_json, qif_text


def test_csv_has_a_running_balance(household: Book) -> None:
    rows = list(csv.DictReader(io.StringIO(csv_text(household, account="Checking"))))
    assert [r["payee"] for r in rows] == ["REWE Markt", "ACME GmbH", "Cafe Lotte", "Landlord"]
    assert [r["amount"] for r in rows] == ["-42.50", "2500.00", "-12.25", "-1100.00"]
    assert rows[-1]["balance"] == "2345.25"


def test_csv_writes_one_row_per_split_piece(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-60.00", payee="Market")
    book.split_transaction(txn.id, {"Food": "-50.00", "Garden": "-10.00"})
    rows = list(csv.DictReader(io.StringIO(csv_text(book))))
    assert [(r["category"], r["amount"]) for r in rows] == [("Food", "-50.00"), ("Garden", "-10.00")]


def test_json_export(household: Book, tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    assert export_json(household, path) == 5
    doc = json.loads(path.read_text("utf-8"))
    assert doc["format"] == "billfold-export/1"
    names = {a["name"]: a for a in doc["accounts"]}
    assert set(names) == {"Checking", "Savings", "Dollars"}
    assert float(names["Checking"]["balance"]) == 2345.25
    assert [float(t["amount"]) for t in doc["transactions"]][:2] == [-42.5, 2500]


def test_json_export_marks_transfers(household: Book) -> None:
    household.transfer("Checking", "Savings", "10.00", "2026-03-10")
    doc = export_document(household)
    assert sum(1 for t in doc["transactions"] if "transfer" in t) == 2


def test_qif(household: Book) -> None:
    text = qif_text(household, account="Checking")
    assert text.startswith("!Account\nNChecking\nTBank\n^\n!Type:Bank\n")
    assert "D03/02/2026\nT-42.50\nPREWE Markt\nLFood:Groceries\n^" in text
    assert "T1000.00\nPOpening Balance" in text


def test_qif_splits(book: Book) -> None:
    book.add_account("Checking")
    txn = book.add_transaction("Checking", "2026-03-02", "-60.00", payee="Market")
    book.split_transaction(txn.id, {"Food": "-50.00", "Garden": "-10.00"})
    assert "SFood\n$-50.00\nSGarden\n$-10.00\n^" in qif_text(book)
