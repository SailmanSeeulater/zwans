"""CLI handlers for accounts, transactions, rules, budgets, recurring entries and rates."""

from __future__ import annotations

from argparse import Namespace

from ..book import Book
from ..money import format_amount, to_amount
from ..rates import read_rates_csv
from ..reconcile import mark_cleared, reconcile
from ..reports.render import table
from ..rules import condition_text
from .output import emit_json, out, transaction_json, transactions_table


def _names(book: Book) -> tuple[dict[str, str], dict[str, str]]:
    currencies = {a.id: a.currency for a in book.accounts.values()}
    names = {a.id: a.name for a in book.accounts.values()}
    return currencies, names


def account(book: Book, args: Namespace) -> bool:
    if args.action == "add":
        acct = book.add_account(
            args.name,
            currency=args.currency or book.settings.base_currency,
            kind=args.kind,
            opening_balance=args.opening,
            opened=args.opened,
        )
        out(f"added {acct.name} ({acct.currency}) as {acct.id}")
        return True
    if args.action == "list":
        rows = []
        for acct in book.list_accounts(include_closed=args.all):
            balance = book.balance(acct)
            rows.append((acct.name, acct.kind, acct.currency,
                         format_amount(balance, acct.currency),
                         "closed" if acct.closed else ""))
        out(table(("Account", "Kind", "Currency", "Balance", ""), rows, "lllrl"))
        return False
    if args.action == "rename":
        acct = book.rename_account(args.name, args.new_name)
        out(f"renamed to {acct.name}")
        return True
    if args.action == "close":
        acct = book.close_account(args.name)
        out(f"closed {acct.name}")
        return True
    raise AssertionError(args.action)


def add(book: Book, args: Namespace) -> bool:
    txn = book.add_transaction(
        args.account,
        args.date or book.clock.today(),
        args.amount,
        payee=args.payee,
        memo=args.memo,
        category=args.category,
        tags=args.tag,
    )
    acct = book.accounts[txn.account]
    category = txn.category or ("split" if txn.splits else "uncategorised")
    out(f"{txn.id}: {format_amount(txn.amount, acct.currency, code=True)} {txn.payee} ({category})")
    return True


def edit(book: Book, args: Namespace) -> bool:
    changes = {}
    for key in ("amount", "date", "payee", "memo", "category"):
        value = getattr(args, key)
        if value is not None:
            changes[key] = value
    if not changes:
        out("nothing to change")
        return False
    txn = book.edit_transaction(args.id, **changes)
    acct = book.accounts[txn.account]
    out(f"{txn.id}: {format_amount(txn.amount, acct.currency, code=True)} {txn.payee}")
    return True


def delete(book: Book, args: Namespace) -> bool:
    gone = book.delete_transaction(args.id)
    out("deleted " + ", ".join(t.id for t in gone))
    return True


def split(book: Book, args: Namespace) -> bool:
    if args.part:
        txn = book.split_transaction(args.id, dict(args.part))
    else:
        txn = book.split_transaction(args.id, args.categories)
    currency = book.accounts[txn.account].currency
    for piece in txn.splits:
        out(f"  {piece.category}: {format_amount(piece.amount, currency)}")
    return True


def transfer(book: Book, args: Namespace) -> bool:
    out_leg, in_leg = book.transfer(
        args.source, args.target, args.amount, args.date or book.clock.today(),
        memo=args.memo, rate=args.rate,
    )
    src, dst = book.accounts[out_leg.account], book.accounts[in_leg.account]
    out(f"moved {format_amount(-out_leg.amount, src.currency, code=True)} from {src.name} "
        f"to {dst.name} ({format_amount(in_leg.amount, dst.currency, code=True)})")
    return True


def balance(book: Book, args: Namespace) -> bool:
    accounts = [book.account(args.account)] if args.account else book.list_accounts()
    if args.json:
        emit_json([
            {"account": a.name, "currency": a.currency, "balance": book.balance(a, args.on)}
            for a in accounts
        ])
        return False
    rows = [(a.name, format_amount(book.balance(a, args.on), a.currency, code=True))
            for a in accounts]
    out(table(("Account", "Balance"), rows, "lr"))
    return False


def list_transactions(book: Book, args: Namespace) -> bool:
    txns = book.transactions_for(args.account, args.start, args.end)
    if args.json:
        emit_json([transaction_json(t) for t in txns])
        return False
    out(transactions_table(txns, *_names(book)))
    return False


def search(book: Book, args: Namespace) -> bool:
    txns = book.search(" ".join(args.query))
    if args.json:
        emit_json([transaction_json(t) for t in txns])
        return False
    out(transactions_table(txns, *_names(book)) if txns else "nothing found")
    return False


def undo(book: Book, args: Namespace) -> bool:
    entry = book.undo()
    out(f"undid: {entry.summary}")
    return True


def history(book: Book, args: Namespace) -> bool:
    for entry in book.history.last(args.n):
        out(f"{entry.seq:>4}  {entry.at}  {entry.summary}")
    return False


def rule(book: Book, args: Namespace) -> bool:
    if args.action == "add":
        split_spec = {name: value for name, value in args.split} or None
        created = book.add_rule(
            args.name, args.conditions, category=args.category, rename=args.rename,
            split=split_spec, tags=args.tag, priority=args.priority,
        )
        out(f"added rule {created.id}")
        return True
    if args.action == "list":
        rows = []
        for item in book.rules.values():
            action = item.set_category or (
                ", ".join(f"{k} {v:g}%" for k, v in item.split.items()) if item.split else ""
            )
            rows.append((item.id, item.name, " & ".join(condition_text(c) for c in item.conditions),
                         action, item.priority))
        out(table(("Id", "Name", "When", "Then", "Priority"), rows, "llllr"))
        return False
    if args.action == "remove":
        book.remove_rule(args.id)
        out(f"removed {args.id}")
        return True
    if args.action == "run":
        changed = book.recategorise(args.account)
        out(f"categorised {changed} transactions")
        return changed > 0
    raise AssertionError(args.action)


def budget(book: Book, args: Namespace) -> bool:
    currency = book.settings.base_currency
    if args.action == "set":
        item = book.budgets.set(args.category, args.month, args.amount, args.rollover)
        out(f"{item.category} {item.month}: {format_amount(item.amount, currency, code=True)}")
        return True
    if args.action == "allocate":
        shares = book.budgets.allocate(args.total, dict(args.weights), args.month, args.rollover)
        for name, share in shares.items():
            out(f"{name}: {format_amount(share, currency)}")
        return True
    if args.action == "status":
        from ..reports.budget_report import render_budget, to_dict

        lines = book.budgets.status(args.month)
        if args.json:
            emit_json(to_dict(lines))
        else:
            out(render_budget(lines, args.month, currency))
        return False
    raise AssertionError(args.action)


def recurring(book: Book, args: Namespace) -> bool:
    if args.action == "add":
        entry = book.recurring.add(
            args.account, args.payee, args.amount, args.frequency, args.start,
            category=args.category, memo=args.memo, end=args.end, instalments=args.instalments,
        )
        out(f"added {entry.id}, first due {entry.next_date.isoformat()}")
        return True
    if args.action == "list":
        rows = []
        for entry in book.recurring.all():
            currency = book.accounts[entry.account].currency
            parts = f"{entry.done}/{entry.instalments}" if entry.instalments else ""
            rows.append((entry.id, entry.payee, format_amount(entry.amount, currency),
                         entry.frequency, entry.next_date.isoformat(), parts,
                         "" if entry.active else "paused"))
        out(table(("Id", "Payee", "Amount", "Every", "Next", "Paid", ""), rows, "llrllrl"))
        return False
    if args.action == "run":
        booked = book.recurring.run(args.until)
        out(f"booked {len(booked)} entries")
        return bool(booked)
    if args.action == "remove":
        book.recurring.remove(args.id)
        out(f"removed {args.id}")
        return True
    raise AssertionError(args.action)


def rate(book: Book, args: Namespace) -> bool:
    if args.action == "set":
        item = book.set_rate(args.base, args.quote, args.rate, args.date)
        out(f"{item.base}->{item.quote} on {item.on.isoformat()}: {item.rate}")
        return True
    if args.action == "import":
        rows = read_rates_csv(args.path)
        for day, base, quote, value in rows:
            book.rates.set(base, quote, value, day)
        out(f"imported {len(rows)} rates")
        return True
    if args.action == "list":
        rows = [(r.on.isoformat(), r.base, r.quote, r.rate) for r in book.rates.all()]
        out(table(("Date", "Base", "Quote", "Rate"), rows, "lllr"))
        return False
    raise AssertionError(args.action)


def convert(book: Book, args: Namespace) -> bool:
    result = book.convert(args.amount, args.base, args.quote, args.date)
    given = to_amount(args.amount, args.base.upper())
    out(f"{format_amount(given, args.base.upper(), code=True)} = "
        f"{format_amount(result, args.quote.upper(), code=True)}")
    return False


def reconcile_command(book: Book, args: Namespace) -> bool:
    changed = mark_cleared(book, args.clear) if args.clear else 0
    result = reconcile(book, args.account, args.balance, args.on or book.clock.today())
    out(result.describe())
    return changed > 0


def alert(book: Book, args: Namespace) -> bool:
    if args.threshold.lower() == "off":
        book.set_large_transaction_alert(None)
        out("large-transaction alerts off")
    else:
        book.set_large_transaction_alert(args.threshold)
        out(f"alerting on transactions of {args.threshold} or more")
    return True
