"""Watching pages, and the outbox notifications land in.

leafwiki doesn't send mail itself. It writes messages to an outbox; whatever delivers them
(a cron job, a chat bot) reads the outbox and drains it.
"""

from __future__ import annotations

from .models import Message
from .storage import Store

EVENTS = ("edited", "renamed", "deleted", "commented", "attached")


class Watchlist:
    def __init__(self, store: Store) -> None:
        self.store = store

    def watchers(self, page_id: str) -> list[str]:
        return sorted(self.store.read_watchers().get(page_id, []))

    def watch(self, page_id: str, user: str) -> bool:
        """Start watching; False if the user already was."""
        everyone = self.store.read_watchers()
        users = set(everyone.get(page_id, []))
        if user in users:
            return False
        users.add(user)
        everyone[page_id] = sorted(users)
        self.store.write_watchers(everyone)
        return True

    def unwatch(self, page_id: str, user: str) -> bool:
        everyone = self.store.read_watchers()
        users = set(everyone.get(page_id, []))
        if user not in users:
            return False
        users.discard(user)
        everyone[page_id] = sorted(users)
        self.store.write_watchers(everyone)
        return True

    def pages_watched_by(self, user: str) -> list[str]:
        return sorted(pid for pid, users in self.store.read_watchers().items() if user in users)

    def drop_page(self, page_id: str) -> list[str]:
        everyone = self.store.read_watchers()
        users = everyone.pop(page_id, [])
        self.store.write_watchers(everyone)
        return users

    def notify(self, page_id: str, title: str, event: str, by: str, at: str) -> list[Message]:
        """Queue one message per watcher, except whoever caused the event."""
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")
        messages = [
            Message(to=user, event=event, page=title, by=by, at=at)
            for user in self.watchers(page_id)
            if user != by
        ]
        self.store.append_messages(messages)
        return messages


class Outbox:
    def __init__(self, store: Store) -> None:
        self.store = store

    def messages(self) -> list[Message]:
        return self.store.read_outbox()

    def drain(self) -> list[Message]:
        messages = self.store.read_outbox()
        self.store.write_outbox([])
        return messages

    def trim(self, limit: int) -> int:
        """Keep the newest ``limit`` messages; returns how many were dropped."""
        messages = self.store.read_outbox()
        if len(messages) <= limit:
            return 0
        self.store.write_outbox(messages[-limit:])
        return len(messages) - limit

    def for_user(self, user: str) -> list[Message]:
        return [m for m in self.store.read_outbox() if m.to == user]
