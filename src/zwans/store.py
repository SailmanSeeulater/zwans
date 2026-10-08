"""Saves sessions in SQLite, so they can be listed, resumed, and rewound."""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from zwans.events import ContextCompacted, Event, TurnEnded, TurnStarted
from zwans.loop import answer_pending_calls
from zwans.messages import Message
from zwans.pricing import CostMeter
from zwans.session import Session

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    workspace TEXT NOT NULL,
    model TEXT NOT NULL,
    system TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    turns INTEGER NOT NULL DEFAULT 0,
    usage TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    session_id TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (session_id, position)
);
"""


class SessionError(Exception):
    pass


@dataclass
class SessionInfo:
    id: str
    workspace: str
    model: str
    system: str  # saved, because a resumed session must send exactly the same system prompt
    title: str = ""
    turns: int = 0
    usage: dict[str, Any] = field(default_factory=dict)  # a CostMeter snapshot
    created_at: str = ""
    updated_at: str = ""


class SessionStore:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def create(self, info: SessionInfo) -> None:
        now = _now()
        with self._db:
            self._db.execute(
                "INSERT INTO sessions (id, created_at, updated_at, workspace, model, system)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (info.id, now, now, info.workspace, info.model, info.system),
            )

    def get(self, id_or_prefix: str) -> SessionInfo:
        """Find a session by its id, or by the start of it when that's unambiguous."""
        rows = self._db.execute(
            "SELECT * FROM sessions WHERE substr(id, 1, length(?)) = ? ORDER BY updated_at DESC",
            (id_or_prefix, id_or_prefix),
        ).fetchall()
        if not rows:
            raise SessionError(f"No saved session starts with {id_or_prefix!r}.")
        exact = [row for row in rows if row["id"] == id_or_prefix]
        if len(rows) > 1 and not exact:
            raise SessionError(
                f"{len(rows)} sessions start with {id_or_prefix!r}. Give more of it."
            )
        return _info((exact or rows)[0])

    def recent(self, limit: int = 20) -> list[SessionInfo]:
        rows = self._db.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_info(row) for row in rows]

    def load_messages(self, session_id: str) -> list[Message]:
        rows = self._db.execute(
            "SELECT body FROM messages WHERE session_id = ? ORDER BY position", (session_id,)
        ).fetchall()
        return [Message.model_validate_json(row["body"]) for row in rows]

    def append_messages(self, session_id: str, start: int, messages: Sequence[Message]) -> None:
        with self._db:
            self._insert(session_id, start, messages)

    def replace_messages(self, session_id: str, messages: Sequence[Message]) -> None:
        """Save a rewritten history, such as after a compaction."""
        with self._db:
            self._db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._insert(session_id, 0, messages)

    def update(self, session_id: str, *, title: str, turns: int, usage: dict[str, Any]) -> None:
        with self._db:
            self._db.execute(
                "UPDATE sessions SET title = ?, turns = ?, usage = ?, updated_at = ? WHERE id = ?",
                (title, turns, json.dumps(usage), _now(), session_id),
            )

    def rewind(self, session_id: str, turn: int) -> None:
        """Delete every turn after `turn`. Turns already summarized away can't be returned to."""
        (first,) = self._db.execute(
            "SELECT MIN(turn) FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        if first is not None and turn < first:
            raise SessionError(
                f"Turns before {first} were summarized when the session was compacted, "
                f"so the earliest turn to rewind to is {first}."
            )
        with self._db:
            self._db.execute(
                "DELETE FROM messages WHERE session_id = ? AND turn > ?", (session_id, turn)
            )
            self._db.execute(
                "UPDATE sessions SET turns = MIN(turns, ?), updated_at = ? WHERE id = ?",
                (turn, _now(), session_id),
            )

    def _insert(self, session_id: str, start: int, messages: Sequence[Message]) -> None:
        self._db.executemany(
            "INSERT INTO messages (session_id, position, turn, body) VALUES (?, ?, ?, ?)",
            [
                (session_id, start + offset, message.turn or 0, message.model_dump_json())
                for offset, message in enumerate(messages)
            ],
        )


def load_session(
    store: SessionStore, id_or_prefix: str, rewind_to: int | None = None
) -> tuple[SessionInfo, list[Message], bool]:
    """Load a saved session to resume it. Returns its info, its messages, and whether tool
    calls left unanswered (Zwans was killed mid-tool) had to be answered."""
    info = store.get(id_or_prefix)
    if rewind_to is not None:
        store.rewind(info.id, rewind_to)
        info = store.get(info.id)
    messages = store.load_messages(info.id)
    return info, messages, answer_pending_calls(messages)


class SessionRecorder:
    """Listens to a session's events and saves its messages and totals as they change."""

    def __init__(
        self,
        store: SessionStore,
        session_id: str,
        session: Session,
        meter: CostMeter,
        saved: int = 0,
        title: str = "",
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.session = session
        self.meter = meter
        self.title = title
        self._saved = saved  # how many of session.messages are already in the database

    def on_event(self, event: Event) -> None:
        if isinstance(event, TurnStarted) and not self.title:
            self.title = event.prompt[:80]
        self.save(rewritten=isinstance(event, ContextCompacted))
        if isinstance(event, TurnEnded):
            self.store.update(
                self.session_id,
                title=self.title,
                turns=self.session.turn,
                usage=self.meter.snapshot(),
            )

    def save(self, rewritten: bool = False) -> None:
        """Save messages added since the last save, or all of them after a rewrite."""
        messages = self.session.messages
        if rewritten or len(messages) < self._saved:
            self._stamp(messages)
            self.store.replace_messages(self.session_id, messages)
        elif len(messages) > self._saved:
            new = messages[self._saved :]
            self._stamp(new)
            self.store.append_messages(self.session_id, self._saved, new)
        self._saved = len(messages)

    def _stamp(self, messages: Sequence[Message]) -> None:
        """Messages the loop added belong to the turn that's running."""
        for message in messages:
            if message.turn is None:
                message.turn = self.session.turn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _info(row: sqlite3.Row) -> SessionInfo:
    return SessionInfo(
        id=row["id"],
        workspace=row["workspace"],
        model=row["model"],
        system=row["system"],
        title=row["title"],
        turns=row["turns"],
        usage=json.loads(row["usage"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
