"""Finding transactions.

A query is a list of terms, all of which must hold:

    coffee              a word in the payee, memo or category
    payee:acme          payee contains "acme"
    cat:Food            in Food or anything under it
    acct:Checking       in that account
    amount:9.99         the amount (ignoring its sign) is 9.99
    amount>100, amount<20, amount>=100, amount<=20
    amount:10..20       between 10 and 20, both included
    since:2026-01-01    on or after that date (until: for on or before)
    #holiday            tagged holiday

The word index is kept up to date as transactions change and rebuilt when a book opens.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .categories import is_under
from .dates import parse_date
from .errors import MoneyError, ValidationError
from .models import Transaction
from .money import parse_amount

_WORD = re.compile(r"[\w']+", re.UNICODE)
_AMOUNT_TERM = re.compile(r"^amount(:|<=|>=|<|>)(.+)$", re.IGNORECASE)


def words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text or "")}


def txn_words(txn: Transaction) -> set[str]:
    found = words(txn.payee) | words(txn.memo)
    for category, _ in txn.category_amounts():
        found |= words((category or "").replace(":", " "))
    return found


class SearchIndex:
    def __init__(self) -> None:
        self._postings: dict[str, set[str]] = {}
        self._words_of: dict[str, set[str]] = {}

    def add(self, txn: Transaction) -> None:
        self.remove(txn.id)
        found = txn_words(txn)
        self._words_of[txn.id] = found
        for word in found:
            self._postings.setdefault(word, set()).add(txn.id)

    def remove(self, txn_id: str) -> None:
        for word in self._words_of.pop(txn_id, ()):
            ids = self._postings.get(word)
            if ids is not None:
                ids.discard(txn_id)
                if not ids:
                    del self._postings[word]

    def rebuild(self, transactions: Iterable[Transaction]) -> None:
        self._postings.clear()
        self._words_of.clear()
        for txn in transactions:
            self.add(txn)

    def lookup(self, word: str) -> set[str]:
        """Ids of transactions with a word starting with `word`."""
        word = word.casefold()
        hits: set[str] = set()
        for candidate, ids in self._postings.items():
            if candidate.startswith(word):
                hits |= ids
        return hits

    def __len__(self) -> int:
        return len(self._words_of)


@dataclass
class Query:
    words: list[str] = field(default_factory=list)
    payee: str | None = None
    category: str | None = None
    account: str | None = None
    amount_eq: Decimal | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    min_inclusive: bool = True
    max_inclusive: bool = True
    since: date | None = None
    until: date | None = None
    tags: list[str] = field(default_factory=list)


def _amount(text: str) -> Decimal:
    try:
        return abs(parse_amount(text))
    except MoneyError:
        raise ValidationError(f"not an amount in search: {text!r}") from None


def parse_query(text: str) -> Query:
    query = Query()
    for term in text.split():
        match = _AMOUNT_TERM.match(term)
        if match:
            op, value = match.groups()
            if op == ":" and ".." in value:
                low, high = (_amount(part) for part in value.split("..", 1))
                query.amount_min, query.amount_max = min(low, high), max(low, high)
            elif op == ":":
                query.amount_eq = _amount(value)
            elif op in (">", ">="):
                query.amount_min, query.min_inclusive = _amount(value), op == ">="
            else:
                query.amount_max, query.max_inclusive = _amount(value), op == "<="
            continue
        key, sep, value = term.partition(":")
        if sep and value:
            key = key.lower()
            if key == "payee":
                query.payee = value
            elif key in ("cat", "category"):
                query.category = value
            elif key in ("acct", "account"):
                query.account = value
            elif key == "since":
                query.since = parse_date(value)
            elif key == "until":
                query.until = parse_date(value)
            else:
                query.words.append(term)
            continue
        if term.startswith("#") and len(term) > 1:
            query.tags.append(term[1:])
        else:
            query.words.append(term)
    return query


def amount_matches(query: Query, amount: Decimal) -> bool:
    size = abs(amount)
    if query.amount_eq is not None and size != query.amount_eq:
        return False
    if query.amount_min is not None:
        if size < query.amount_min or (size == query.amount_min and not query.min_inclusive):
            return False
    if query.amount_max is not None:
        if size > query.amount_max or (size == query.amount_max and not query.max_inclusive):
            return False
    return True


def run_query(
    query: Query,
    transactions: dict[str, Transaction],
    index: SearchIndex,
    account_names: dict[str, str],
) -> list[Transaction]:
    candidates: set[str] | None = None
    for word in query.words:
        for part in words(word):
            hits = index.lookup(part)
            candidates = hits if candidates is None else candidates & hits
    pool = (
        transactions.values()
        if candidates is None
        else (transactions[i] for i in candidates if i in transactions)
    )
    found = []
    for txn in pool:
        if query.payee and query.payee.casefold() not in txn.payee.casefold():
            continue
        if query.category and not any(
            is_under(category, query.category) for category, _ in txn.category_amounts()
        ):
            continue
        if query.account and account_names.get(txn.account, "").casefold() != query.account.casefold():
            continue
        if query.since and txn.date < query.since:
            continue
        if query.until and txn.date > query.until:
            continue
        if query.tags and not all(tag in txn.tags for tag in query.tags):
            continue
        if not amount_matches(query, txn.amount):
            continue
        found.append(txn)
    found.sort(key=lambda t: (t.date, t.id))
    return found
