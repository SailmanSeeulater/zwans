"""`Book`, the service everything else goes through."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import rules as rulebook
from .audit import History, HistoryEntry, revive
from .balances import BalanceCache
from .budgets import BudgetBook
from .categories import CategoryTree, clean, is_under
from .clock import SystemClock, stamp
from .currencies import get_currency, normalise_code
from .dates import month_key, parse_date
from .errors import DuplicateName, NotFound, ValidationError
from .ids import IdSource
from .models import ACCOUNT_KINDS, Account, Rule, Settings, Split, Transaction
from .money import (
    decimal_number,
    format_amount,
    is_zero,
    round_half_up,
    same_amount,
    share_evenly,
    to_amount,
)
from .notifications import (
    BUDGET_EXCEEDED,
    LARGE_TRANSACTION,
    Event,
    Notifier,
    budget_exceeded_payload,
    large_transaction_payload,
)
from .rates import RateTable
from .recurring import Recurring
from .search import SearchIndex, parse_query, run_query

EDITABLE = ("date", "amount", "payee", "memo", "category", "tags", "cleared", "account")


class Book:
    def __init__(self, *, clock=None, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else None
        self.clock = clock or SystemClock()
        self.settings = Settings()
        self.ids = IdSource()
        self.accounts: dict[str, Account] = {}
        self.transactions: dict[str, Transaction] = {}
        self.categories = CategoryTree()
        self.rules: dict[str, Rule] = {}
        self.rates = RateTable()
        self.history = History(self.settings.history_limit)
        self.notifier = Notifier()
        self.balances = BalanceCache()
        self.index = SearchIndex()
        self.budgets = BudgetBook(self)
        self.recurring = Recurring(self)
        self._by_account: dict[str, set[str]] = {}

    # -- files -----------------------------------------------------------------------

    @classmethod
    def open(cls, path: Path | str, *, clock=None) -> Book:
        """Load a data file, or start an empty book that will be saved there."""
        from .storage import load_book

        return load_book(Path(path), clock=clock)

    def save(self, path: Path | str | None = None) -> Path:
        from .storage import save_book

        target = Path(path) if path else self.path
        if target is None:
            raise ValidationError("this book has no file yet; give a path")
        self.path = target
        save_book(self, target)
        return target

    # -- amounts ---------------------------------------------------------------------

    def _amount(self, value: object, currency: str) -> Decimal:
        return to_amount(value, currency)

    def money(self, amount: Decimal, account: str | Account) -> str:
        acct = account if isinstance(account, Account) else self.account(account)
        return format_amount(amount, acct.currency)

    # -- accounts --------------------------------------------------------------------

    def add_account(
        self,
        name: str,
        currency: str = "EUR",
        kind: str = "checking",
        opening_balance: object = 0,
        opened: date | str | None = None,
        notes: str = "",
    ) -> Account:
        name = name.strip()
        if not name:
            raise ValidationError("an account needs a name")
        if self._find_account(name) is not None:
            raise DuplicateName(f"there is already an account called {name!r}")
        if kind not in ACCOUNT_KINDS:
            raise ValidationError(f"kind must be one of {', '.join(ACCOUNT_KINDS)}")
        currency = normalise_code(currency)
        account = Account(
            id=self.ids.next("acc"),
            name=name,
            currency=currency,
            kind=kind,
            opening_balance=self._amount(opening_balance, currency),
            opened=parse_date(opened) if opened else self.clock.today(),
            notes=notes,
        )
        self.accounts[account.id] = account
        self._by_account[account.id] = set()
        return account

    def _find_account(self, ref: str) -> Account | None:
        if ref in self.accounts:
            return self.accounts[ref]
        wanted = ref.strip().casefold()
        for account in self.accounts.values():
            if account.name.casefold() == wanted:
                return account
        return None

    def account(self, ref: str | Account) -> Account:
        if isinstance(ref, Account):
            return ref
        found = self._find_account(ref)
        if found is None:
            raise NotFound(f"no account {ref!r}")
        return found

    def list_accounts(self, include_closed: bool = False) -> list[Account]:
        accounts = [a for a in self.accounts.values() if include_closed or not a.closed]
        return sorted(accounts, key=lambda a: a.name.casefold())

    def rename_account(self, ref: str, new_name: str) -> Account:
        account = self.account(ref)
        other = self._find_account(new_name)
        if other is not None and other.id != account.id:
            raise DuplicateName(f"there is already an account called {new_name!r}")
        account.name = new_name.strip()
        return account

    def close_account(self, ref: str) -> Account:
        account = self.account(ref)
        balance = self.balance(account)
        if not is_zero(balance, account.currency):
            raise ValidationError(
                f"{account.name} still holds {format_amount(balance, account.currency, code=True)}"
            )
        account.closed = True
        return account

    # -- reading transactions ----------------------------------------------------------

    def transaction(self, txn_id: str) -> Transaction:
        try:
            return self.transactions[txn_id]
        except KeyError:
            raise NotFound(f"no transaction {txn_id!r}") from None

    def transactions_for(
        self,
        account: str | Account | None = None,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Transaction]:
        if account is None:
            pool: Iterable[Transaction] = self.transactions.values()
        else:
            acct = self.account(account)
            pool = (self.transactions[i] for i in self._by_account.get(acct.id, ()))
        found = [
            t for t in pool
            if (start is None or t.date >= start) and (end is None or t.date <= end)
        ]
        found.sort(key=lambda t: (t.date, int(t.id.rpartition("-")[2] or 0)))
        return found

    def balance(self, account: str | Account, on: date | None = None) -> Decimal:
        acct = self.account(account)
        ids = self._by_account.get(acct.id, set())
        if on is None:
            cached = self.balances.get(acct.id, len(ids))
            if cached is not None:
                return cached
        total = acct.opening_balance
        for txn_id in ids:
            txn = self.transactions[txn_id]
            if on is None or txn.date <= on:
                total += txn.amount
        if on is None:
            self.balances.put(acct.id, total, len(ids))
        return total

    # -- changing transactions -----------------------------------------------------------

    def _insert(self, txn: Transaction) -> None:
        self.transactions[txn.id] = txn
        self._by_account.setdefault(txn.account, set()).add(txn.id)
        self.balances.apply(txn.account, txn.amount, 1)
        self.index.add(txn)

    def _remove(self, txn: Transaction) -> None:
        del self.transactions[txn.id]
        self._by_account.get(txn.account, set()).discard(txn.id)
        self.balances.apply(txn.account, -txn.amount, -1)
        self.index.remove(txn.id)

    def _record(self, op: str, summary: str, before, after) -> None:
        self.history.record(op, summary, before, after, stamp(self.clock.now()))

    def _clean_splits(self, splits, total: Decimal, currency: str) -> list[Split]:
        cleaned = []
        for item in splits:
            if isinstance(item, Split):
                category, amount, memo = item.category, item.amount, item.memo
            elif isinstance(item, dict):
                category, amount, memo = item.get("category"), item["amount"], item.get("memo", "")
            else:
                category, amount = item
                memo = ""
            cleaned.append(
                Split(self.categories.ensure(category), self._amount(amount, currency), memo)
            )
        if cleaned and not same_amount(sum((s.amount for s in cleaned), Decimal(0)), total, currency):
            raise ValidationError("the splits don't add up to the transaction amount")
        return cleaned

    def new_transaction(
        self,
        account: str | Account,
        on: date | str,
        amount: object,
        payee: str = "",
        memo: str = "",
        category: str | None = None,
        splits: Iterable | None = None,
        tags: Iterable[str] = (),
        *,
        cleared: bool = False,
        import_ref: str | None = None,
        apply_rules: bool = True,
    ) -> Transaction:
        """Build a transaction without adding it (imports look at it first)."""
        acct = self.account(account)
        if acct.closed:
            raise ValidationError(f"{acct.name} is closed")
        value = self._amount(amount, acct.currency)
        txn = Transaction(
            id=self.ids.next("txn"),
            account=acct.id,
            date=parse_date(on),
            amount=value,
            payee=payee.strip(),
            memo=memo.strip(),
            category=self.categories.ensure(category),
            splits=self._clean_splits(splits or (), value, acct.currency),
            tags=list(tags),
            cleared=cleared,
            import_ref=import_ref,
        )
        if apply_rules and txn.category is None and not txn.splits:
            self.apply_rules_to(txn)
        return txn

    def add_transaction(self, account, on, amount, payee: str = "", memo: str = "",
                        category: str | None = None, splits: Iterable | None = None,
                        tags: Iterable[str] = (), **options) -> Transaction:
        txn = self.new_transaction(
            account, on, amount, payee, memo, category, splits, tags, **options
        )
        return self.commit([txn], "add", f"added {txn.id}")[0]

    def commit(self, txns: list[Transaction], op: str, summary: str) -> list[Transaction]:
        """Add built transactions as one change (one undo step, one round of alerts)."""
        keys = self._budget_keys(txns)
        before = self._budget_spending(keys)
        for txn in txns:
            self._insert(txn)
        self._record(op, summary, [], txns)
        self._alert_budgets(keys, before)
        for txn in txns:
            self._alert_large(txn)
        return txns

    def edit_transaction(self, txn_id: str, **changes) -> Transaction:
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise ValidationError(f"can't edit {', '.join(sorted(unknown))}")
        old = self.transaction(txn_id)
        if old.is_transfer and ({"amount", "account"} & set(changes)):
            raise ValidationError("delete and redo a transfer to change its amount or account")
        new = old.copy()
        account = self.account(changes.get("account", old.account))
        new.account = account.id
        if "amount" in changes:
            if old.splits:
                raise ValidationError("this transaction is split; change the splits instead")
            new.amount = self._amount(changes["amount"], account.currency)
        if "date" in changes:
            new.date = parse_date(changes["date"])
        if "payee" in changes:
            new.payee = str(changes["payee"]).strip()
        if "memo" in changes:
            new.memo = str(changes["memo"]).strip()
        if "category" in changes:
            new.category = self.categories.ensure(changes["category"])
            new.splits = []
        if "tags" in changes:
            new.tags = list(changes["tags"])
        if "cleared" in changes:
            new.cleared = bool(changes["cleared"])
        keys = self._budget_keys([old, new])
        before = self._budget_spending(keys)
        self._remove(old)
        self._insert(new)
        self._record("edit", f"edited {txn_id}", [old], [new])
        self._alert_budgets(keys, before)
        return new

    def delete_transaction(self, txn_id: str) -> list[Transaction]:
        txn = self.transaction(txn_id)
        gone = [txn]
        if txn.transfer_id:
            gone = [t for t in self.transactions.values() if t.transfer_id == txn.transfer_id]
        for item in gone:
            self._remove(item)
        self._record("delete", f"deleted {', '.join(t.id for t in gone)}", gone, [])
        return gone

    def split_transaction(self, txn_id: str, parts) -> Transaction:
        """Split evenly over a list of categories, or by a {category: amount} mapping."""
        old = self.transaction(txn_id)
        currency = self.accounts[old.account].currency
        if isinstance(parts, dict):
            splits = self._clean_splits(parts.items(), old.amount, currency)
        else:
            names = [clean(name) for name in parts]
            if len(names) < 2:
                raise ValidationError("split over at least two categories")
            amounts = share_evenly(old.amount, len(names), currency)
            splits = [Split(self.categories.add(n), a) for n, a in zip(names, amounts)]
        new = old.copy()
        new.splits = splits
        new.category = None
        self._remove(old)
        self._insert(new)
        self._record("split", f"split {txn_id}", [old], [new])
        return new

    def transfer(
        self,
        source: str | Account,
        target: str | Account,
        amount: object,
        on: date | str,
        memo: str = "",
        rate: object | None = None,
    ) -> tuple[Transaction, Transaction]:
        """Move money between two accounts, converting when their currencies differ."""
        src, dst = self.account(source), self.account(target)
        if src.id == dst.id:
            raise ValidationError("a transfer needs two different accounts")
        day = parse_date(on)
        sent = self._amount(amount, src.currency)
        if sent <= 0:
            raise ValidationError("transfer a positive amount")
        if src.currency == dst.currency:
            received = sent
        elif rate is not None:
            received = round_half_up(sent * decimal_number(rate, "rate"), dst.currency)
        else:
            received = self.rates.convert(sent, src.currency, dst.currency, day)
        link = self.ids.next("xfer")
        out_leg = Transaction(self.ids.next("txn"), src.id, day, -sent,
                              payee=f"Transfer to {dst.name}", memo=memo, transfer_id=link)
        in_leg = Transaction(self.ids.next("txn"), dst.id, day, received,
                             payee=f"Transfer from {src.name}", memo=memo, transfer_id=link)
        self.commit([out_leg, in_leg], "transfer", f"transfer {link}")
        return out_leg, in_leg

    def convert(self, amount: object, base: str, quote: str, on: date | None = None) -> Decimal:
        value = self._amount(amount, base)
        return self.rates.convert(value, base, quote, on or self.clock.today())

    def set_rate(self, base: str, quote: str, rate: object, on: date | str | None = None):
        return self.rates.set(base, quote, rate, parse_date(on) if on else self.clock.today())

    # -- undo ------------------------------------------------------------------------------

    def undo(self) -> HistoryEntry:
        entry = self.history.pop()
        for data in entry.after:
            current = self.transactions.get(data["id"])
            if current is not None:
                self._remove(current)
        for data in entry.before:
            self._insert(revive(data, self._currency_for(data)))
        if entry.op == "recurring":
            self.recurring.rewind([revive(data, self._currency_for(data)) for data in entry.after])
        return entry

    def _currency_for(self, data: dict) -> str:
        account = self.accounts.get(data.get("account", ""))
        return account.currency if account else self.settings.base_currency

    # -- rules -----------------------------------------------------------------------------

    def add_rule(
        self,
        name: str,
        conditions: Iterable[str],
        category: str | None = None,
        rename: str | None = None,
        split: dict[str, object] | None = None,
        tags: Iterable[str] = (),
        priority: int = 100,
    ) -> Rule:
        parsed = [rulebook.parse_condition(text) for text in conditions]
        if not parsed:
            raise ValidationError("a rule needs at least one condition")
        if not (category or rename or split or tags):
            raise ValidationError("a rule needs something to do")
        rule = Rule(
            id=self.ids.next("rule"),
            name=name,
            conditions=parsed,
            set_category=self.categories.ensure(category),
            rename_payee=rename,
            split=rulebook.check_split(split) if split else None,
            add_tags=list(tags),
            priority=priority,
        )
        if rule.split:
            for name in rule.split:
                self.categories.add(name)
        self.rules[rule.id] = rule
        return rule

    def remove_rule(self, rule_id: str) -> Rule:
        try:
            return self.rules.pop(rule_id)
        except KeyError:
            raise NotFound(f"no rule {rule_id!r}") from None

    def apply_rules_to(self, txn: Transaction) -> Rule | None:
        account = self.accounts[txn.account]
        rule = rulebook.first_match(self.rules.values(), txn, account.name)
        if rule is not None:
            rulebook.apply(rule, txn, account.currency)
        return rule

    def recategorise(self, account: str | None = None) -> int:
        """Run the rules over every uncategorised transaction; returns how many changed."""
        changed = 0
        for txn in self.transactions_for(account):
            if txn.category is not None or txn.splits or txn.is_transfer:
                continue
            new = txn.copy()
            if self.apply_rules_to(new) is None:
                continue
            self._remove(txn)
            self._insert(new)
            self._record("edit", f"rules changed {txn.id}", [txn], [new])
            changed += 1
        return changed

    # -- search ------------------------------------------------------------------------------

    def search(self, text: str) -> list[Transaction]:
        names = {a.id: a.name for a in self.accounts.values()}
        return run_query(parse_query(text), self.transactions, self.index, names)

    # -- alerts ------------------------------------------------------------------------------

    def on_alert(self, callback: Callable[[Event], None]) -> Callable[[], None]:
        return self.notifier.subscribe(callback)

    def set_large_transaction_alert(self, amount: object | None) -> None:
        if amount is None:
            self.settings.large_transaction = None
        else:
            self.settings.large_transaction = self._amount(amount, self.settings.base_currency)

    def _budget_keys(self, txns: Iterable[Transaction]) -> set[tuple[str, str]]:
        keys = set()
        base = self.settings.base_currency
        for txn in txns:
            account = self.accounts.get(txn.account)
            if txn.is_transfer or account is None or account.currency != base:
                continue
            month = month_key(txn.date)
            for budget in self.budgets.for_month(month):
                if any(is_under(cat, budget.category) for cat, _ in txn.category_amounts()):
                    keys.add((budget.category, month))
        return keys

    def _budget_spending(self, keys: set[tuple[str, str]]) -> dict[tuple[str, str], Decimal]:
        return {key: self.budgets.line(*key).remaining for key in keys}

    def _alert_budgets(self, keys, before: dict[tuple[str, str], Decimal]) -> None:
        for key in sorted(keys):
            line = self.budgets.line(*key)
            if line.remaining < 0 <= before[key]:
                payload = budget_exceeded_payload(
                    line.category, line.month, line.available, line.spent,
                    self.settings.base_currency,
                )
                self.notifier.emit(BUDGET_EXCEEDED, payload)

    def _alert_large(self, txn: Transaction) -> None:
        threshold = self.settings.large_transaction
        if threshold is None or txn.is_transfer:
            return
        account = self.accounts[txn.account]
        if account.currency != self.settings.base_currency:
            return
        if abs(txn.amount) >= threshold:
            payload = large_transaction_payload(txn, account, threshold)
            self.notifier.emit(LARGE_TRANSACTION, payload)

    # -- misc ------------------------------------------------------------------------------------

    def currency_of(self, account: str | Account) -> str:
        return self.account(account).currency

    def exponent_of(self, account: str | Account) -> int:
        return get_currency(self.currency_of(account)).exponent

    def rebuild_caches(self) -> None:
        """Recompute the account map and search index from the transactions."""
        self._by_account = {account_id: set() for account_id in self.accounts}
        for txn in self.transactions.values():
            self._by_account.setdefault(txn.account, set()).add(txn.id)
        self.index.rebuild(self.transactions.values())
