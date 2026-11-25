"""`python -m taskgraph`: build a project described in a taskfile.

A taskfile is a Python file that defines `project`, a taskgraph.Project. Paths in it are
relative to the taskfile's directory.
"""

import argparse
import runpy
import sys
from pathlib import Path

from taskgraph.fs import DiskFS
from taskgraph.graph import build_order, downstream
from taskgraph.project import Project, ProjectError
from taskgraph.runner import Builder
from taskgraph.state import STATE_FILE


def load(path: Path) -> Project:
    namespace = runpy.run_path(str(path))
    project = namespace.get("project")
    if not isinstance(project, Project):
        raise ProjectError(f"{path} does not define `project`")
    return project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taskgraph")
    parser.add_argument("-f", "--file", default="Taskfile.py", help="the taskfile")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="bring targets up to date")
    build.add_argument("targets", nargs="*")
    build.add_argument("-v", "--verbose", action="store_true")
    status = commands.add_parser("status", help="what would run, and why")
    status.add_argument("targets", nargs="*")
    commands.add_parser("graph", help="print the tasks and what they need")
    commands.add_parser("clean", help="delete every output and the build state")
    args = parser.parse_args(argv)

    taskfile = Path(args.file)
    try:
        project = load(taskfile)
    except (OSError, ProjectError) as error:
        print(f"taskgraph: {error}", file=sys.stderr)
        return 2
    fs = DiskFS(taskfile.parent)

    try:
        if args.command == "build":
            return _build(project, fs, args.targets or None, args.verbose)
        if args.command == "status":
            builder = Builder(project, fs)
            for name, why in builder.status(args.targets or None).items():
                print(f"{name}: {why}")
            return 0
        if args.command == "graph":
            return _graph(project)
        if args.command == "clean":
            return _clean(project, fs)
    except ProjectError as error:
        print(f"taskgraph: {error}", file=sys.stderr)
        return 2
    return 0


def _build(project: Project, fs: DiskFS, targets: list[str] | None, verbose: bool) -> int:
    result = Builder(project, fs, verbose=verbose).build(targets)
    for name in result.ran:
        if name in result.failed:
            print(f"FAILED {name}: {result.failed[name]}")
        else:
            print(f"ran    {name}")
    for name in result.blocked:
        print(f"skip   {name} (something it needs failed)")
    print(f"{len(result.ran)} ran, {len(result.up_to_date)} up to date, "
          f"{len(result.failed)} failed")
    return 0 if result.ok else 1


def _graph(project: Project) -> int:
    users = downstream(project)
    for task in build_order(project):
        needs = ", ".join(project.upstream(task)) or "-"
        used_by = ", ".join(users[task.name]) or "-"
        print(f"{task.name}\n  needs: {needs}\n  used by: {used_by}")
    return 0


def _clean(project: Project, fs: DiskFS) -> int:
    removed = 0
    for path in sorted(project.producers) + [STATE_FILE]:
        if fs.exists(path):
            fs.delete(path)
            removed += 1
    print(f"removed {removed} files")
    return 0
