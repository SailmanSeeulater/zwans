"""The command-line interface."""

import argparse
import json
import sys
from pathlib import Path

from todo.store import Store, Task, TaskNotFound


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo")
    parser.add_argument("--file", type=Path, default=Path("todo.json"), help="the todo file")
    commands = parser.add_subparsers(dest="command", required=True)

    add = commands.add_parser("add", help="add a task")
    add.add_argument("title")

    done = commands.add_parser("done", help="mark a task as done")
    done.add_argument("id", type=int)

    show = commands.add_parser("list", help="show the tasks")
    show.add_argument("--pending", action="store_true", help="only tasks not yet done")
    show.add_argument("--json", action="store_true", help="print the tasks as a JSON array")
    return parser


def format_task(task: Task) -> str:
    mark = "x" if task.done else " "
    return f"[{mark}] {task.id} {task.title}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.file)

    if args.command == "add":
        task = store.add(args.title)
        print(f"Added {task.id}: {task.title}")
    elif args.command == "done":
        try:
            task = store.mark_done(args.id)
        except TaskNotFound:
            print(f"No task with id {args.id}", file=sys.stderr)
            return 1
        print(f"Done {task.id}: {task.title}")
    elif args.command == "list":
        tasks = store.load()
        if args.pending:
            tasks = [task for task in tasks if not task.done]
        if args.json:
            data = [{"id": task.id, "title": task.title, "done": task.done} for task in tasks]
            print(json.dumps(data, ensure_ascii=False))
        else:
            for task in tasks:
                print(format_task(task))
    return 0
