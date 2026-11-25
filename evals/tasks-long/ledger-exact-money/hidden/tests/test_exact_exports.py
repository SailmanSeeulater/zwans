"""Rule 6: exports write amounts as plain text with exactly the currency's places."""

import csv
import io
import json
from pathlib import Path

from billfold import Book
from billfold.exporters import csv_text, export_document, export_json, qif_text


def rows(book: Book, **options) -> list[dict]:
    return list(csv.DictReader(io.StringIO(csv_text(book, **options))))


def test_csv_amounts_and_running_balance(pennies: Book) -> None:
    checking = rows(pennies, account="Checking")
    assert [r["amount"] for r in checking] == ["-0.10", "-0.20", "-19.99", "1234.56"]
    assert [r["balance"] for r in checking] == ["0.60", "0.40", "-19.59", "1214.97"]


def test_csv_yen_has_no_decimals(pennies: Book) -> None:
    yen = rows(pennies, account="Yen")
    assert [(r["amount"], r["balance"]) for r in yen] == [("-1200", "13800")]


def test_csv_split_pieces(pennies: Book) -> None:
    txn = pennies.add_transaction("Checking", "2026-03-06", "-0.05", payee="Shop")
    pennies.split_transaction(txn.id, ["A", "B", "C"])
    pieces = [r for r in rows(pennies, account="Checking") if r["payee"] == "Shop"]
    assert [r["amount"] for r in pieces] == ["-0.02", "-0.02", "-0.01"]
    assert pieces[-1]["balance"] == "1214.92"


def test_json_export_writes_strings(pennies: Book, tmp_path: Path) -> None:
    export_json(pennies, tmp_path / "out.json")
    doc = json.loads((tmp_path / "out.json").read_text("utf-8"))
    accounts = {a["name"]: a for a in doc["accounts"]}
    assert accounts["Checking"]["balance"] == "1214.97"
    assert accounts["Checking"]["opening_balance"] == "0.70"
    assert accounts["Yen"]["balance"] == "13800"
    assert [t["amount"] for t in doc["transactions"]] == [
        "-0.10", "-0.20", "-19.99", "1234.56", "-1200"]


def test_json_export_splits(pennies: Book) -> None:
    txn = pennies.add_transaction("Checking", "2026-03-06", "-33.33", payee="Market")
    pennies.split_transaction(txn.id, {"Food": "-20.00", "Household": "-13.33"})
    doc = json.loads(json.dumps(export_document(pennies)))
    item = next(t for t in doc["transactions"] if t["payee"] == "Market")
    assert [s["amount"] for s in item["splits"]] == ["-20.00", "-13.33"]
    assert item["amount"] == "-33.33"


def test_qif_amounts(pennies: Book) -> None:
    text = qif_text(pennies, account="Checking")
    assert "T0.70\nPOpening Balance" in text
    assert "D03/02/2026\nT-0.10\nPKiosk" in text
    assert "T1234.56\nPACME GmbH" in text


def test_qif_yen_has_no_decimals(pennies: Book) -> None:
    text = qif_text(pennies, account="Yen")
    assert "T15000\nPOpening Balance" in text
    assert "D03/05/2026\nT-1200\nPRamen Ya" in text


def test_qif_split_amounts_in_yen(pennies: Book) -> None:
    txn = pennies.add_transaction("Yen", "2026-03-06", "-1001", payee="Konbini")
    pennies.split_transaction(txn.id, ["Food", "Drinks"])
    assert "SFood\n$-501\nSDrinks\n$-500\n^" in qif_text(pennies, account="Yen")
