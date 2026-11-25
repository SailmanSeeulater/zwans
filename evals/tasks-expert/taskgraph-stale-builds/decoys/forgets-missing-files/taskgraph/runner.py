"""The builder: decides which tasks need to run, runs them, and remembers what they did."""

import traceback
from dataclasses import dataclass, field

from taskgraph.context import TaskContext
from taskgraph.fs import FileSystem
from taskgraph.graph import build_order
from taskgraph.project import Project, Task, TaskFailed
from taskgraph.state import Record, State, digest, fingerprint


@dataclass
class BuildResult:
    ran: list[str] = field(default_factory=list)  # in the order they ran
    up_to_date: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # task -> error message
    blocked: list[str] = field(default_factory=list)  # not run: something it needs failed

    @property
    def ok(self) -> bool:
        return not self.failed and not self.blocked


@dataclass
class Stats:
    executions: int = 0  # actions run, across every build of this Builder


class Builder:
    def __init__(self, project: Project, fs: FileSystem, verbose: bool = False) -> None:
        self.project = project
        self.fs = fs
        self.verbose = verbose
        self.stats = Stats()
        self.log: list[str] = []  # every task this Builder ran, in order

    def build(self, targets: list[str] | None = None) -> BuildResult:
        order = build_order(self.project, targets)
        state = State.load(self.fs)
        result = BuildResult()
        broken: set[str] = set()
        try:
            for task in order:
                if any(name in broken for name in self.project.upstream(task)):
                    broken.add(task.name)
                    result.blocked.append(task.name)
                    continue
                if self.up_to_date(task, state.records.get(task.name)):
                    result.up_to_date.append(task.name)
                    continue
                error = self._run(task, state)
                result.ran.append(task.name)
                if error is not None:
                    broken.add(task.name)
                    result.failed[task.name] = error
        finally:
            state.save(self.fs)
        return result

    def status(self, targets: list[str] | None = None) -> dict[str, str]:
        """Each task's state as of now: "up to date" or why it would run.

        This looks at each task on its own, as if nothing upstream ran first.
        """
        state = State.load(self.fs)
        found = {}
        for task in build_order(self.project, targets):
            found[task.name] = self.why(task, state.records.get(task.name)) or "up to date"
        return found

    # -- deciding

    def up_to_date(self, task: Task, record: Record | None) -> bool:
        return self.why(task, record) is None

    def why(self, task: Task, record: Record | None) -> str | None:
        """None if `task` needn't run, else the reason it must."""
        if record is None:
            return "never built"
        if record.fingerprint != fingerprint(task):
            return "definition changed"
        for path, seen in record.reads.items():
            if self._digest(path) != seen:
                return f"{path} changed"
        for path, wrote in record.outputs.items():
            if self._digest(path) != wrote:
                return f"output {path} missing or changed"
        return None

    def _digest(self, path: str) -> str | None:
        try:
            return digest(self.fs.read(path))
        except FileNotFoundError:
            return None

    # -- running

    def _run(self, task: Task, state: State) -> str | None:
        """Run the task's action; None if it worked, else the error message."""
        self.stats.executions += 1
        self.log.append(task.name)
        if self.verbose:
            print(f"running {task.name}")
        context = TaskContext(self.project, task, self.fs)
        for path in task.inputs:
            context.reads[path] = self._digest(path)
        try:
            task.action(context)
            missing = [path for path in task.outputs if path not in context.written]
            if missing:
                raise TaskFailed(f"{task.name} did not write {', '.join(missing)}")
        except Exception as error:  # an action may fail in any way
            state.records.pop(task.name, None)
            if isinstance(error, TaskFailed):
                return str(error)
            return "".join(traceback.format_exception_only(error)).strip()
        state.records[task.name] = Record(
            fingerprint=fingerprint(task),
            reads=dict(context.reads),
            outputs=dict(context.written),
            built_at=self.fs.now(),
        )
        return None
