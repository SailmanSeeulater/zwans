"""Reading and writing the todo file."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Task:
    id: int
    title: str
    done: bool = False


class TaskNotFound(Exception):
    pass


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Task(**item) for item in raw]

    def save(self, tasks: list[Task]) -> None:
        data = [asdict(task) for task in tasks]
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def add(self, title: str) -> Task:
        tasks = self.load()
        next_id = max((task.id for task in tasks), default=0) + 1
        task = Task(id=next_id, title=title)
        tasks.append(task)
        self.save(tasks)
        return task

    def mark_done(self, task_id: int) -> Task:
        tasks = self.load()
        for task in tasks:
            if task.id == task_id:
                task.done = True
                self.save(tasks)
                return task
        raise TaskNotFound(task_id)
