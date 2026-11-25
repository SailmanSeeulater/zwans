"""The context every service call runs in: the store, the clock and who is acting."""

from __future__ import annotations

from typing import Any

from . import audit, config
from .clock import Clock
from .models import Agent, AuditEntry
from .store import Store


class Context:
    """Who is doing something, and with what.

    ``actor`` is the id of the agent acting, or None for the system itself (the mail
    gateway, scheduled jobs, setup scripts and the CLI when no ``--as`` is given).
    """

    def __init__(self, store: Store, clock: Clock, actor: str | None = None) -> None:
        self.store = store
        self.clock = clock
        self.actor = actor

    @property
    def is_system(self) -> bool:
        return self.actor is None

    @property
    def actor_name(self) -> str:
        return self.actor or audit.SYSTEM

    @property
    def role(self) -> str | None:
        """The acting agent's role; None for the system."""
        if self.actor is None:
            return None
        return self.store.agent(self.actor).role

    @property
    def agent(self) -> Agent | None:
        if self.actor is None:
            return None
        return self.store.agent(self.actor)

    def now(self) -> str:
        return self.clock()

    def setting(self, key: str) -> Any:
        return config.get(self.store.settings, key)

    def record(self, action: str, target: str, /, **details: Any) -> AuditEntry:
        return audit.record(self.store, self.now(), self.actor, action, target, details)

    def as_system(self) -> Context:
        return Context(self.store, self.clock, None)

    def as_agent(self, agent_id: str) -> Context:
        return Context(self.store, self.clock, agent_id)
