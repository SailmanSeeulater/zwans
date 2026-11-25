"""Categorisation rules.

A rule has conditions (all must hold) and actions. Rules are tried in priority order
(lowest number first, then oldest); the first rule that matches is applied and the rest
are skipped. Conditions are written as text:

    payee~netflix      payee contains "netflix" (case doesn't matter)
    payee=Netflix      payee is exactly that (case doesn't matter)
    memo^rent          memo starts with "rent"
    payee/^ACME \\d+/   payee matches a regular expression
    account=Checking   the transaction is in that account
    amount=9.99        the amount (ignoring its sign) is 9.99
    amount<20, amount<=20, amount>5, amount>=5
    amount=10..20      between 10 and 20, both included
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .categories import clean
from .currencies import get_currency
from .errors import ValidationError
from .models import Condition, Rule, Split, Transaction

_TEXT = re.compile(r"^(payee|memo|account)\s*(~|=|\^)\s*(.+)$", re.IGNORECASE)
_REGEX = re.compile(r"^(payee|memo)\s*/(.+)/$", re.IGNORECASE)
_AMOUNT = re.compile(r"^amount\s*(<=|>=|=|<|>)\s*(.+)$", re.IGNORECASE)
_TEXT_OPS = {"~": "contains", "=": "equals", "^": "starts"}
_NUMBER_OPS = {"=": "eq", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}


def _number(text: str) -> float:
    try:
        return float(text.strip().replace(",", ""))
    except ValueError:
        raise ValidationError(f"not a number in rule: {text!r}") from None


def parse_condition(text: str) -> Condition:
    text = text.strip()
    match = _REGEX.match(text)
    if match:
        field, pattern = match.groups()
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValidationError(f"bad pattern {pattern!r}: {error}") from None
        return Condition(field.lower(), "regex", pattern)
    match = _AMOUNT.match(text)
    if match:
        op, value = match.groups()
        if op == "=" and ".." in value:
            low, high = (_number(part) for part in value.split("..", 1))
            if low > high:
                low, high = high, low
            return Condition("amount", "between", (low, high))
        return Condition("amount", _NUMBER_OPS[op], _number(value))
    match = _TEXT.match(text)
    if match:
        field, op, value = match.groups()
        return Condition(field.lower(), _TEXT_OPS[op], value.strip())
    raise ValidationError(f"can't read rule condition {text!r}")


def condition_text(condition: Condition) -> str:
    """The inverse of parse_condition."""
    if condition.op == "regex":
        return f"{condition.field}/{condition.value}/"
    if condition.field == "amount":
        if condition.op == "between":
            low, high = condition.value
            return f"amount={low}..{high}"
        symbol = {v: k for k, v in _NUMBER_OPS.items()}[condition.op]
        return f"amount{symbol}{condition.value}"
    symbol = {v: k for k, v in _TEXT_OPS.items()}[condition.op]
    return f"{condition.field}{symbol}{condition.value}"


def _text_holds(op: str, actual: str, wanted: str) -> bool:
    if op == "regex":
        return re.search(wanted, actual, re.IGNORECASE) is not None
    actual, wanted = actual.casefold(), wanted.casefold()
    if op == "contains":
        return wanted in actual
    if op == "equals":
        return actual == wanted
    if op == "starts":
        return actual.startswith(wanted)
    raise ValidationError(f"unknown text test {op!r}")


def _number_holds(op: str, actual: float, wanted: object) -> bool:
    if op == "between":
        low, high = wanted
        return low <= actual <= high
    if op == "eq":
        return actual == wanted
    if op == "lt":
        return actual < wanted
    if op == "le":
        return actual <= wanted
    if op == "gt":
        return actual > wanted
    if op == "ge":
        return actual >= wanted
    raise ValidationError(f"unknown amount test {op!r}")


def matches(rule: Rule, txn: Transaction, account_name: str) -> bool:
    if not rule.enabled or not rule.conditions:
        return False
    for condition in rule.conditions:
        if condition.field == "amount":
            if not _number_holds(condition.op, abs(txn.amount), condition.value):
                return False
            continue
        actual = {"payee": txn.payee, "memo": txn.memo, "account": account_name}[condition.field]
        if not _text_holds(condition.op, actual or "", str(condition.value)):
            return False
    return True


def ordered(rules: Iterable[Rule]) -> list[Rule]:
    def key(rule: Rule) -> tuple[int, int]:
        _, _, number = rule.id.rpartition("-")
        return rule.priority, int(number) if number.isdigit() else 0

    return sorted(rules, key=key)


def check_split(split: dict[str, float]) -> dict[str, float]:
    if not split:
        raise ValidationError("a split needs at least one category")
    cleaned = {clean(name): float(percent) for name, percent in split.items()}
    if any(percent <= 0 for percent in cleaned.values()):
        raise ValidationError("split percentages must be positive")
    if abs(sum(cleaned.values()) - 100) > 1e-9:
        raise ValidationError("split percentages must add up to 100")
    return cleaned


def split_by_percent(amount: float, split: dict[str, float], currency: str) -> list[Split]:
    """Share an amount out by percentage; the last category takes what rounding leaves."""
    places = get_currency(currency).exponent
    parts: list[Split] = []
    given = 0.0
    items = list(split.items())
    for index, (category, percent) in enumerate(items):
        if index == len(items) - 1:
            share = round(amount - given, places)
        else:
            share = round(amount * percent / 100, places)
        given += share
        parts.append(Split(category, share))
    return parts


def apply(rule: Rule, txn: Transaction, currency: str) -> None:
    if rule.rename_payee:
        txn.payee = rule.rename_payee
    if rule.split:
        txn.splits = split_by_percent(txn.amount, rule.split, currency)
        txn.category = None
    elif rule.set_category:
        txn.category = rule.set_category
        txn.splits = []
    for tag in rule.add_tags:
        if tag not in txn.tags:
            txn.tags.append(tag)


def first_match(rules: Iterable[Rule], txn: Transaction, account_name: str) -> Rule | None:
    for rule in ordered(rules):
        if matches(rule, txn, account_name):
            return rule
    return None
