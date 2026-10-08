"""Writes every event of a session to a JSONL file, one JSON object per line."""

import json
from datetime import UTC, datetime
from pathlib import Path

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
