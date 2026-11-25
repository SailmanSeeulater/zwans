"""A slow, obviously-right build for the tests to compare against, written from the README
and sharing no code with taskgraph: plain dicts for files and records, every decision made
from file contents."""

from dataclasses import dataclass, field
from typing import Any, Callable


class Failed(Exception):
    pass


@dataclass
class Spec:
    name: str
    action: Callable[[Any], None]
    inputs: list[str]
    outputs: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def definition(self) -> tuple:
        action = f"{self.action.__module__}.{self.action.__qualname__}"
        return (self.name, action, self.version, tuple(self.inputs), tuple(self.outputs),
                repr(sorted(self.params.items())))


class Context:
    """The same interface an action gets from taskgraph."""

    def __init__(self, spec: Spec, files: dict[str, str], producers: dict[str, str]) -> None:
        self.spec = spec
        self.files = files
        self.producers = producers
        self.reads: dict[str, str | None] = {}
        self.written: dict[str, str] = {}

    params = property(lambda self: self.spec.params)
    inputs = property(lambda self: self.spec.inputs)
    outputs = property(lambda self: self.spec.outputs)

    def read(self, path: str) -> str | None:
        producer = self.producers.get(path)
        if producer not in (None, self.spec.name) and path not in self.spec.inputs:
            raise Failed(f"undeclared read of {path}")
        text = self.files.get(path)
        self.reads[path] = text
        return text

    def write(self, path: str, text: str) -> None:
        if path not in self.spec.outputs:
            raise Failed(f"undeclared write of {path}")
        self.files[path] = text
        self.written[path] = text


@dataclass
class Record:
    definition: tuple
    reads: dict[str, str | None]
    outputs: dict[str, str]


class Reference:
    def __init__(self) -> None:
        self.records: dict[str, Record] = {}

    def build(self, specs: list[Spec], files: dict[str, str]) -> tuple[set, set, set]:
        """Build every task; `files` is changed in place. (ran, failed, blocked)."""
        producers = {path: spec.name for spec in specs for path in spec.outputs}
        by_name = {spec.name: spec for spec in specs}
        needs = {
            spec.name: {producers[p] for p in spec.inputs if p in producers} for spec in specs
        }
        ran: set[str] = set()
        failed: set[str] = set()
        blocked: set[str] = set()
        done: set[str] = set()
        while len(done) < len(specs):
            ready = sorted(n for n in by_name if n not in done and needs[n] <= done)
            assert ready, "the generated project has a cycle"
            for name in ready:
                done.add(name)
                spec = by_name[name]
                if needs[name] & (failed | blocked):
                    blocked.add(name)
                    continue
                if self.fresh(spec, files):
                    continue
                ran.add(name)
                context = Context(spec, files, producers)
                for path in spec.inputs:
                    context.reads[path] = files.get(path)
                try:
                    spec.action(context)
                    if set(context.written) != set(spec.outputs):
                        raise Failed("an output was not written")
                except Exception:
                    failed.add(name)
                    self.records.pop(name, None)
                    continue
                self.records[name] = Record(spec.definition(), dict(context.reads),
                                            dict(context.written))
        return ran, failed, blocked

    def fresh(self, spec: Spec, files: dict[str, str]) -> bool:
        record = self.records.get(spec.name)
        if record is None or record.definition != spec.definition():
            return False
        if any(files.get(path) != text for path, text in record.reads.items()):
            return False
        return all(files.get(path) == text for path, text in record.outputs.items())
