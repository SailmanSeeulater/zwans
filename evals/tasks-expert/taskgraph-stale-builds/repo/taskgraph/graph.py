"""Putting tasks in an order where each comes after the tasks it needs."""

from taskgraph.project import Project, Task


def build_order(project: Project, targets: list[str] | None = None) -> list[Task]:
    """`targets` (every task if None) and everything they need, upstream first."""
    names = list(project.tasks) if targets is None else list(targets)
    for name in names:
        project[name]  # unknown names fail here, before anything runs
    seen: set[str] = set()
    order: list[Task] = []

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        for upstream in project.upstream(project[name]):
            visit(upstream)
        order.append(project[name])

    for name in names:
        visit(name)
    return order


def downstream(project: Project) -> dict[str, list[str]]:
    """For each task, the tasks that declare one of its outputs as an input."""
    found: dict[str, list[str]] = {name: [] for name in project.tasks}
    for task in project.tasks.values():
        for producer in project.upstream(task):
            found[producer].append(task.name)
    return found
