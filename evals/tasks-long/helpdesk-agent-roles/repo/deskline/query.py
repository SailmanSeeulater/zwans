"""The ticket search language.

A query is a list of terms, all of which must match:

    status:open,pending  priority:high  queue:billing  tag:vip  -tag:spam
    assignee:maria  assignee:me  assignee:none  customer:C-4  requester:jane
    email:example.org  phone:555  created>2026-03-01  updated<2026-04-01
    is:breached  is:unassigned  is:active  "exact phrase"  printer

Bare words and quoted phrases match the subject and the public conversation. A leading
``-`` negates any term. ``me`` means the agent running the search.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass

from .clock import format_time, parse_time
from .errors import QueryError
from .models import PRIORITIES, STATUSES, Ticket
from .store import Store

Predicate = Callable[[Store, Ticket], bool]

FIELDS = (
    "status",
    "priority",
    "queue",
    "tag",
    "assignee",
    "customer",
    "requester",
    "email",
    "phone",
    "is",
)
DATE_FIELDS = ("created", "updated")
SORTS = {
    "updated": (lambda t: t.updated_at, True),
    "created": (lambda t: t.created_at, True),
    "priority": (lambda t: PRIORITIES.index(t.priority), True),
    "id": (lambda t: int(t.id.split("-")[1]), False),
}


@dataclass(frozen=True)
class Term:
    field: str  # "" for free text
    op: str  # ":", ">" or "<"
    value: str
    negated: bool = False


def tokenize(text: str) -> list[Term]:
    try:
        words = shlex.split(text)
    except ValueError as exc:
        raise QueryError(f"bad query: {exc}") from None
    terms = []
    for word in words:
        negated = word.startswith("-") and len(word) > 1
        if negated:
            word = word[1:]
        for op in (":", ">", "<"):
            name, sep, value = word.partition(op)
            if sep and name.isalpha() and name.lower() in FIELDS + DATE_FIELDS:
                name = name.lower()
                if op != ":" and name not in DATE_FIELDS:
                    raise QueryError(f"{name} does not compare with {op}")
                if op == ":" and name in DATE_FIELDS:
                    raise QueryError(f"use {name}> or {name}< for dates")
                if not value:
                    raise QueryError(f"{name}{op} needs a value")
                terms.append(Term(name, op, value, negated))
                break
        else:
            terms.append(Term("", ":", word, negated))
    return terms


def _requester(store: Store, ticket: Ticket):
    return store.customers.get(ticket.customer_id)


def _term_predicate(term: Term, me: str | None) -> Predicate:
    field, value = term.field, term.value
    lowered = value.lower()
    choices = [v.strip().lower() for v in value.split(",") if v.strip()]

    if field == "status":
        bad = [c for c in choices if c not in STATUSES]
        if bad:
            raise QueryError(f"unknown status {bad[0]!r}")
        return lambda s, t: t.status in choices
    if field == "priority":
        bad = [c for c in choices if c not in PRIORITIES]
        if bad:
            raise QueryError(f"unknown priority {bad[0]!r}")
        return lambda s, t: t.priority in choices
    if field == "queue":
        return lambda s, t: t.queue in choices
    if field == "tag":
        return lambda s, t: any(c in t.tags for c in choices)
    if field == "assignee":
        wanted = []
        for c in choices:
            if c == "me":
                if me is None:
                    raise QueryError("assignee:me needs an agent")
                wanted.append(me)
            elif c == "none":
                wanted.append(None)
            else:
                wanted.append(c)
        return lambda s, t: t.assignee in wanted
    if field == "customer":
        return lambda s, t: t.customer_id.lower() in choices
    if field == "requester":
        def by_name(s: Store, t: Ticket) -> bool:
            customer = _requester(s, t)
            return customer is not None and lowered in customer.name.lower()
        return by_name
    if field == "email":
        def by_email(s: Store, t: Ticket) -> bool:
            customer = _requester(s, t)
            return customer is not None and lowered in customer.email.lower()
        return by_email
    if field == "phone":
        digits = "".join(ch for ch in value if ch.isdigit())
        def by_phone(s: Store, t: Ticket) -> bool:
            customer = _requester(s, t)
            if customer is None or not digits:
                return False
            return digits in "".join(ch for ch in customer.phone if ch.isdigit())
        return by_phone
    if field == "is":
        if lowered == "breached":
            return lambda s, t: bool(t.breaches)
        if lowered == "unassigned":
            return lambda s, t: t.assignee is None
        if lowered == "active":
            return lambda s, t: t.is_active
        if lowered == "merged":
            return lambda s, t: t.merged_into is not None
        raise QueryError(f"unknown is:{value}")
    if field in DATE_FIELDS:
        try:
            bound = format_time(parse_time(value))
        except ValueError:
            raise QueryError(f"bad date {value!r}") from None
        attr = "created_at" if field == "created" else "updated_at"
        if term.op == ">":
            return lambda s, t: getattr(t, attr) >= bound
        return lambda s, t: getattr(t, attr) < bound

    def text(s: Store, t: Ticket) -> bool:
        if lowered in t.subject.lower():
            return True
        return any(lowered in c.body.lower() for c in t.comments if c.public)

    return text


def compile_query(text: str, *, me: str | None = None) -> Predicate:
    predicates = []
    for term in tokenize(text):
        predicate = _term_predicate(term, me)
        if term.negated:
            predicate = (lambda p: lambda s, t: not p(s, t))(predicate)
        predicates.append(predicate)
    return lambda s, t: all(p(s, t) for p in predicates)


def terms_on(text: str, fields: tuple[str, ...]) -> list[Term]:
    return [term for term in tokenize(text) if term.field in fields]


def select(store: Store, predicate: Predicate, sort: str = "updated") -> list[Ticket]:
    if sort not in SORTS:
        raise QueryError(f"cannot sort by {sort!r}")
    key, reverse = SORTS[sort]
    found = [t for t in store.tickets.values() if predicate(store, t)]
    found.sort(key=lambda t: int(t.id.split("-")[1]))
    found.sort(key=key, reverse=reverse)
    return found
