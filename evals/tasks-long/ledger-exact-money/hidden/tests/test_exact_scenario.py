"""Random histories against a model that counts in whole minor units.

Every step adds, edits, deletes, splits, transfers (within EUR and into USD or JPY at the
stored rates), undoes, or saves and reopens the book. After each step every balance must
be the exact Decimal the model expects; at the end the exports, the monthly report and
the net-worth report must agree with the model too.
"""

import copy
import csv
import io
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from billfold import Book, FixedClock, NothingToUndo
from billfold.exporters import csv_text, export_document
from billfold.reports import monthly_report, net_worth

PLACES = {"EUR": 2, "USD": 2, "JPY": 0}
ACCOUNTS = {"Checking": ("EUR", 100000), "Savings": ("EUR", 0), "Dollars": ("USD", 5000),
            "Yen": ("JPY", 100000)}
RATES = {("EUR", "USD"): Fraction(10825, 10000), ("EUR", "JPY"): Fraction(1615, 10)}
CATEGORIES = ["Food", "Food:Snacks", "Rent", "Fun", "Salary", None]


def text(units: int, currency: str) -> str:
    places = PLACES[currency]
    sign = "-" if units < 0 else ""
    units = abs(units)
    if not places:
        return f"{sign}{units}"
    return f"{sign}{units // 10**places}.{units % 10**places:0{places}d}"


def half_up(value: Fraction) -> int:
    sign = -1 if value < 0 else 1
    value = abs(value)
    whole = value.numerator // value.denominator
    if value - whole >= Fraction(1, 2):
        whole += 1
    return sign * whole


def convert(units: int, base: str, quote: str) -> Fraction:
    """Exact amount of `quote` minor units for `units` of base."""
    major = Fraction(units, 10 ** PLACES[base])
    if base == quote:
        pass
    elif (base, quote) in RATES:
        major *= RATES[(base, quote)]
    else:
        major /= RATES[(quote, base)]
    return major * 10 ** PLACES[quote]


def even(units: int, parts: int) -> list[int]:
    sign = -1 if units < 0 else 1
    base, extra = divmod(abs(units), parts)
    return [sign * (base + (1 if i < extra else 0)) for i in range(parts)]


class Model:
    def __init__(self) -> None:
        self.txns: dict[str, dict] = {}
        self.undo: list[dict] = []

    def change(self) -> None:
        self.undo.append(copy.deepcopy(self.txns))
        del self.undo[:-50]

    def balance(self, name: str) -> int:
        return ACCOUNTS[name][1] + sum(t["units"] for t in self.txns.values() if t["account"] == name)


def amount_arg(rng: random.Random, currency: str) -> int:
    if PLACES[currency] == 0:
        return rng.choice([-1, 1]) * rng.randint(1, 30000)
    return rng.choice([-1, -1, 1]) * rng.choice([rng.randint(1, 30), rng.randint(1, 250000)])


def check_balances(book: Book, model: Model) -> None:
    for name, (currency, _) in ACCOUNTS.items():
        got = book.balance(name)
        want = text(model.balance(name), currency)
        assert isinstance(got, Decimal) and str(got) == want, (name, got, want)


@pytest.mark.parametrize("seed", range(6))
def test_random_history(seed: int, tmp_path: Path) -> None:
    rng = random.Random(seed)
    path = tmp_path / "book.json"
    book = Book(clock=FixedClock("2026-03-01"), path=path)
    for name, (currency, opening) in ACCOUNTS.items():
        book.add_account(name, currency=currency, opening_balance=text(opening, currency),
                         opened="2026-01-01")
    book.set_rate("EUR", "USD", "1.0825", "2026-01-01")
    book.set_rate("EUR", "JPY", "161.5", "2026-01-01")
    model = Model()

    for step in range(160):
        op = rng.choices(["add", "edit", "delete", "split", "transfer", "undo", "reopen"],
                         [30, 10, 8, 8, 14, 8, 3])[0]
        day = date(2026, 3, 1) + timedelta(days=rng.randint(0, 27))
        plain = [i for i, t in model.txns.items() if not t["link"] and not t["splits"]]
        if op == "add" or (op in ("edit", "split") and not plain) or (op == "delete" and not model.txns):
            name = rng.choice(list(ACCOUNTS))
            currency = ACCOUNTS[name][0]
            units = amount_arg(rng, currency)
            category = rng.choice(CATEGORIES)
            txn = book.add_transaction(name, day, text(units, currency), payee=f"p{step}",
                                       category=category)
            model.change()
            model.txns[txn.id] = {"account": name, "units": units, "date": day,
                                  "category": category, "splits": None, "link": None}
        elif op == "edit":
            txn_id = rng.choice(plain)
            currency = ACCOUNTS[model.txns[txn_id]["account"]][0]
            units = amount_arg(rng, currency)
            book.edit_transaction(txn_id, amount=text(units, currency))
            model.change()
            model.txns[txn_id]["units"] = units
        elif op == "delete":
            txn_id = rng.choice(sorted(model.txns))
            book.delete_transaction(txn_id)
            model.change()
            link = model.txns[txn_id]["link"]
            for other in [i for i, t in model.txns.items() if i == txn_id or (link and t["link"] == link)]:
                del model.txns[other]
        elif op == "split":
            txn_id = rng.choice(plain)
            parts = rng.randint(2, 4)
            names = ["Food", "Fun", "Rent", "Gifts"][:parts]
            book.split_transaction(txn_id, names)
            model.change()
            model.txns[txn_id]["splits"] = list(zip(names, even(model.txns[txn_id]["units"], parts)))
        elif op == "transfer":
            target = rng.choice(["Savings", "Savings", "Dollars", "Yen"])
            units = rng.choice([rng.randint(1, 40), rng.randint(1, 50000)])
            out_leg, in_leg = book.transfer("Checking", target, text(units, "EUR"), day)
            quote = ACCOUNTS[target][0]
            received = half_up(convert(units, "EUR", quote))
            model.change()
            link = f"L{step}"
            model.txns[out_leg.id] = {"account": "Checking", "units": -units, "date": day,
                                      "category": None, "splits": None, "link": link}
            model.txns[in_leg.id] = {"account": target, "units": received, "date": day,
                                     "category": None, "splits": None, "link": link}
        elif op == "undo":
            if model.undo:
                book.undo()
                model.txns = model.undo.pop()
            else:
                with pytest.raises(NothingToUndo):
                    book.undo()
        elif op == "reopen":
            book.save()
            book = Book.open(path, clock=FixedClock("2026-03-01"))
        check_balances(book, model)

    book.save()
    book = Book.open(path, clock=FixedClock("2026-03-01"))
    check_balances(book, model)
    assert json.loads(path.read_text("utf-8"))["version"] == 3

    for name, (currency, _) in ACCOUNTS.items():
        rows = list(csv.DictReader(io.StringIO(csv_text(book, account=name))))
        if rows:
            assert rows[-1]["balance"] == text(model.balance(name), currency)

    doc = export_document(book)
    names = {a["id"]: a["name"] for a in doc["accounts"]}
    exported = sorted((names[t["account"]], t["amount"]) for t in doc["transactions"])
    expected = sorted((t["account"], text(t["units"], ACCOUNTS[t["account"]][0]))
                      for t in model.txns.values())
    assert exported == expected

    income = expenses = 0
    for t in model.txns.values():
        if t["link"] or ACCOUNTS[t["account"]][0] != "EUR":
            continue
        pieces = [units for _, units in t["splits"]] if t["splits"] else [t["units"]]
        for units in pieces:
            if units >= 0:
                income += units
            else:
                expenses -= units
    report = monthly_report(book, "2026-03")
    assert (str(report.income), str(report.expenses)) == (text(income, "EUR"), text(expenses, "EUR"))
    assert str(report.daily_average) == text(half_up(Fraction(expenses, 31)), "EUR")

    worth = net_worth(book, on=date(2026, 3, 31))
    exact_total = sum(
        (convert(model.balance(name), currency, "EUR") if currency != "EUR"
         else Fraction(model.balance(name))) for name, (currency, _) in ACCOUNTS.items())
    assert str(worth.total) == text(half_up(exact_total), "EUR")
    for line in worth.lines:
        currency = ACCOUNTS[line.account][0]
        want = model.balance(line.account)
        if currency != "EUR":
            want = half_up(convert(want, currency, "EUR"))
        assert str(line.converted) == text(want, "EUR")
