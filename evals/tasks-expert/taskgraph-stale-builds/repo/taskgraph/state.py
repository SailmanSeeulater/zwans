"""What the builder remembers between builds, kept in `.taskgraph/state.json`."""

import hashlib
import json
from dataclasses import asdict, dataclass, field

from taskgraph.fs import FileSystem
from taskgraph.project import Task

STATE_FILE = ".taskgraph/state.json"
FORMAT = 3


def digest(text: str | None) -> str | None:
    """A content hash of a file's text, or None for a file that doesn't exist."""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def fingerprint(task: Task) -> str:
    """A hash of everything that defines the task."""
    definition = {
        "name": task.name,
        "action": task.action_name,
        "version": task.version,
        "inputs": list(task.inputs),
        "outputs": list(task.outputs),
    }
    return digest(json.dumps(definition, sort_keys=True)) or ""


@dataclass
class Record:
    """What a task's last successful run read and wrote."""

    fingerprint: str
    reads: dict[str, str | None] = field(default_factory=dict)  # path -> digest or None
    outputs: dict[str, str] = field(default_factory=dict)  # path -> digest
    built_at: float = 0.0


class State:
    def __init__(self, records: dict[str, Record] | None = None) -> None:
        self.records: dict[str, Record] = records or {}

    @classmethod
    def load(cls, fs: FileSystem) -> "State":
        try:
            raw = json.loads(fs.read(STATE_FILE))
        except FileNotFoundError:
            return cls()
        except ValueError:
            return cls()  # a damaged state file means building everything again
        if raw.get("format") != FORMAT:
            return cls()
        return cls({name: Record(**record) for name, record in raw["records"].items()})

    def save(self, fs: FileSystem) -> None:
        raw = {
            "format": FORMAT,
            "records": {name: asdict(record) for name, record in sorted(self.records.items())},
        }
        fs.write(STATE_FILE, json.dumps(raw, indent=1, sort_keys=True))
