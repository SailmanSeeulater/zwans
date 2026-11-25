"""The in-memory state of a helpdesk, with all-or-nothing transactions.

The store holds every record as model objects. Changes happen inside
``with store.transaction():``; if the block raises, the store is put back exactly as it
was when the outermost transaction began, and nothing is written to disk. When the
outermost transaction commits, the store calls its ``on_commit`` hook (the JSON file
backend uses it to save).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from ..errors import NotFound
from ..models import (
    Agent,
    AuditEntry,
    Customer,
    Macro,
    OutgoingMail,
    Queue,
    SavedSearch,
    SlaPolicy,
    Survey,
    Team,
    Ticket,
)

COLLECTIONS: dict[str, type] = {
    "customers": Customer,
    "agents": Agent,
    "teams": Team,
    "queues": Queue,
    "tickets": Ticket,
    "macros": Macro,
    "searches": SavedSearch,
    "surveys": Survey,
}

KEYED = {"sla": SlaPolicy}


class Store:
    def __init__(self) -> None:
        self.customers: dict[str, Customer] = {}
        self.agents: dict[str, Agent] = {}
        self.teams: dict[str, Team] = {}
        self.queues: dict[str, Queue] = {}
        self.tickets: dict[str, Ticket] = {}
        self.macros: dict[str, Macro] = {}
        self.searches: dict[str, SavedSearch] = {}
        self.surveys: dict[str, Survey] = {}
        self.sla: dict[str, SlaPolicy] = {}
        self.audit: list[AuditEntry] = []
        self.outbox: list[OutgoingMail] = []
        self.counters: dict[str, int] = {}
        self.settings: dict[str, Any] = {}
        self.on_commit: Callable[[Store], None] | None = None
        self._depth = 0
        self._saved: dict[str, Any] | None = None
        self._afterwards: list[Callable[[Store], None]] = []

    # -- transactions ---------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[Store]:
        if self._depth == 0:
            self._saved = self._state()
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._restore(self._saved)
                self._saved = None
                if self._run_afterwards() and self.on_commit is not None:
                    self.on_commit(self)
            raise
        self._depth -= 1
        if self._depth == 0:
            self._saved = None
            self._run_afterwards()
            if self.on_commit is not None:
                self.on_commit(self)

    def afterwards(self, work: Callable[[Store], None]) -> None:
        """Run ``work`` when the outermost transaction ends, whether it commits or not.

        For records that must outlive the change they describe (a refused operation is
        rolled back, but the refusal is kept).
        """
        if self._depth == 0:
            with self.transaction():
                work(self)
        else:
            self._afterwards.append(work)

    def _run_afterwards(self) -> bool:
        pending, self._afterwards = self._afterwards, []
        for work in pending:
            work(self)
        return bool(pending)

    @property
    def in_transaction(self) -> bool:
        return self._depth > 0

    def _state(self) -> dict[str, Any]:
        names = list(COLLECTIONS) + ["sla", "audit", "outbox", "counters", "settings"]
        return {name: copy.deepcopy(getattr(self, name)) for name in names}

    def _restore(self, state: dict[str, Any] | None) -> None:
        if state is None:
            return
        for name, value in state.items():
            setattr(self, name, value)

    # -- ids ------------------------------------------------------------------------

    def next_id(self, kind: str, prefix: str) -> str:
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return f"{prefix}-{self.counters[kind]}"

    def next_number(self, kind: str) -> int:
        self.counters[kind] = self.counters.get(kind, 0) + 1
        return self.counters[kind]

    # -- lookups --------------------------------------------------------------------

    def ticket(self, ticket_id: str) -> Ticket:
        try:
            return self.tickets[ticket_id]
        except KeyError:
            raise NotFound("ticket", ticket_id) from None

    def customer(self, customer_id: str) -> Customer:
        try:
            return self.customers[customer_id]
        except KeyError:
            raise NotFound("customer", customer_id) from None

    def agent(self, agent_id: str) -> Agent:
        try:
            return self.agents[agent_id]
        except KeyError:
            raise NotFound("agent", agent_id) from None

    def team(self, team_id: str) -> Team:
        try:
            return self.teams[team_id]
        except KeyError:
            raise NotFound("team", team_id) from None

    def queue(self, queue_id: str) -> Queue:
        try:
            return self.queues[queue_id]
        except KeyError:
            raise NotFound("queue", queue_id) from None

    def macro(self, macro_id: str) -> Macro:
        try:
            return self.macros[macro_id]
        except KeyError:
            raise NotFound("macro", macro_id) from None

    def saved_search(self, search_id: str) -> SavedSearch:
        try:
            return self.searches[search_id]
        except KeyError:
            raise NotFound("saved search", search_id) from None

    def customer_by_email(self, email: str) -> Customer | None:
        wanted = email.strip().lower()
        for customer in self.customers.values():
            if customer.email.lower() == wanted:
                return customer
        return None

    # -- (de)serialising ------------------------------------------------------------

    def to_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for name in COLLECTIONS:
            data[name] = [record.to_dict() for record in getattr(self, name).values()]
        data["sla"] = [policy.to_dict() for policy in self.sla.values()]
        data["audit"] = [entry.to_dict() for entry in self.audit]
        data["outbox"] = [mail.to_dict() for mail in self.outbox]
        data["counters"] = dict(self.counters)
        data["settings"] = dict(self.settings)
        return data

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> Store:
        store = cls()
        for name, model in COLLECTIONS.items():
            records = {}
            for raw in data.get(name, []):
                record = model.from_dict(raw)
                records[record.id] = record
            setattr(store, name, records)
        store.sla = {
            raw["priority"]: SlaPolicy.from_dict(raw) for raw in data.get("sla", [])
        }
        store.audit = [AuditEntry.from_dict(raw) for raw in data.get("audit", [])]
        store.outbox = [OutgoingMail.from_dict(raw) for raw in data.get("outbox", [])]
        store.counters = dict(data.get("counters", {}))
        store.settings = dict(data.get("settings", {}))
        return store
