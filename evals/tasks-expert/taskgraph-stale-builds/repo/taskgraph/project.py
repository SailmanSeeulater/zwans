"""Tasks and the project that holds them."""

from dataclasses import dataclass, field
from typing import Any, Callable


class ProjectError(Exception):
    """A project that can't be built as defined (duplicate names or outputs, ...)."""


class CycleError(ProjectError):
    """Tasks that need each other's outputs. `cycle` names them in order."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__("dependency cycle: " + " -> ".join(cycle + cycle[:1]))


class TaskFailed(Exception):
    """Raise from an action to fail the task with a message."""


@dataclass
class Task:
    """One step of a build.

    `inputs` are the files the task declares it reads; `outputs` the files it must write.
    The action may read other files too (see TaskContext.read). `params` are settings
    handed to the action; `version` is bumped by hand when the action's code changes.
    """

    name: str
    action: Callable[[Any], None]
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name or any(ch.isspace() for ch in self.name):
            raise ProjectError(f"bad task name {self.name!r}")
        if not self.outputs:
            raise ProjectError(f"task {self.name} has no outputs")
        if len(set(self.outputs)) != len(self.outputs):
            raise ProjectError(f"task {self.name} lists an output twice")

    @property
    def action_name(self) -> str:
        action = self.action
        return f"{getattr(action, '__module__', '?')}.{getattr(action, '__qualname__', '?')}"


class Project:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.producers: dict[str, str] = {}  # output path -> task name

    def add(self, task: Task) -> Task:
        if task.name in self.tasks:
            raise ProjectError(f"two tasks named {task.name}")
        for path in task.outputs:
            if path in self.producers:
                raise ProjectError(
                    f"{path} is an output of both {self.producers[path]} and {task.name}"
                )
        self.tasks[task.name] = task
        for path in task.outputs:
            self.producers[path] = task.name
        return task

    def task(self, name: str | None = None, **options: Any):
        """Decorator form of add(): the function is the action."""

        def register(action: Callable[[Any], None]) -> Callable[[Any], None]:
            self.add(Task(name or action.__name__.replace("_", "-"), action, **options))
            return action

        return register

    def upstream(self, task: Task) -> list[str]:
        """The tasks that produce `task`'s declared inputs."""
        found: list[str] = []
        for path in task.inputs:
            producer = self.producers.get(path)
            if producer is not None and producer not in found:
                found.append(producer)
        return found

    def __getitem__(self, name: str) -> Task:
        try:
            return self.tasks[name]
        except KeyError:
            raise ProjectError(f"no task named {name}") from None
