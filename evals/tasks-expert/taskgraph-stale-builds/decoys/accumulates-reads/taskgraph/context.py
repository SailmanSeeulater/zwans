"""The object an action gets: its way to read and write files."""

from typing import Any

from taskgraph.fs import FileSystem
from taskgraph.project import Project, Task, TaskFailed
from taskgraph.state import digest


class TaskContext:
    """Reads and writes for one run of one task, and a note of every file touched."""

    def __init__(self, project: Project, task: Task, fs: FileSystem) -> None:
        self.project = project
        self.task = task
        self.fs = fs
        self.reads: dict[str, str | None] = {}
        self.written: dict[str, str] = {}

    @property
    def params(self) -> dict[str, Any]:
        return self.task.params

    @property
    def inputs(self) -> list[str]:
        return self.task.inputs

    @property
    def outputs(self) -> list[str]:
        return self.task.outputs

    def read(self, path: str) -> str | None:
        """The file's text, or None if it doesn't exist.

        Any file may be read, declared or not, except another task's output that isn't
        among this task's declared inputs.
        """
        producer = self.project.producers.get(path)
        if producer is not None and producer != self.task.name and path not in self.task.inputs:
            raise TaskFailed(
                f"{self.task.name} reads {path}, an output of {producer}; "
                "declare it as an input"
            )
        try:
            text = self.fs.read(path)
        except FileNotFoundError:
            text = None
        self.reads[path] = digest(text)
        return text

    def write(self, path: str, text: str) -> None:
        if path not in self.task.outputs:
            raise TaskFailed(f"{self.task.name} writes {path}, which is not one of its outputs")
        self.fs.write(path, text)
        self.written[path] = digest(text) or ""
