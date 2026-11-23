"""Writes every event of a session to a JSONL file, one JSON object per line."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zwans.events import Event


class TranscriptWriter:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("a", encoding="utf-8")

    def on_event(self, event: Event) -> None:
        time = datetime.now(UTC).isoformat(timespec="milliseconds")
        record = {"time": time, **event.model_dump(mode="json")}
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()  # keep the file complete even if the process is killed

    def close(self) -> None:
        self._file.close()


def read(path: Path) -> list[dict[str, Any]]:
    """A session's events from its transcript, without the turns a rewind dropped."""
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # a line cut short when Zwans was killed
        if not isinstance(record, dict):
            continue
        if record.get("type") == "rewound":
            cut = _first_turn_after(events, int(record.get("turn") or 0))
            del events[cut:]
        else:
            events.append(record)
    return events


def _first_turn_after(events: list[dict[str, Any]], turn: int) -> int:
    """Where the first turn after `turn` starts in `events`, or the end when there's none.
    Transcripts from before turns were numbered count them instead."""
    count = 0
    for index, event in enumerate(events):
        if event.get("type") == "turn_started":
            count += 1
            if (event.get("turn") or count) > turn:
                return index
    return len(events)
