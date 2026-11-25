"""Putting tasks in an order where each comes after the tasks it needs."""

from taskgraph.project import CycleError, Project, Task

WHITE, GREY, BLACK = 0, 1, 2


def build_order(project: Project, targets: list[str] | None = None) -> list[Task]:
    """`targets` (every task if None) and everything they need, upstream first.

    Raises CycleError if the tasks involved need each other in a circle.
    """
    names = list(project.tasks) if targets is None else list(targets)
    for name in names:
        project[name]  # unknown names fail here, before anything runs
    colour: dict[str, int] = {}
    order: list[Task] = []
    for root in names:
        if colour.get(root, WHITE) != WHITE:
            continue
        # Each stack entry is a task and the upstream tasks still to visit.
        stack = [(root, list(reversed(project.upstream(project[root]))))]
        colour[root] = GREY
        while stack:
            name, pending = stack[-1]
            if not pending:
                stack.pop()
                colour[name] = BLACK
                order.append(project[name])
                continue
            nxt = pending.pop()
            state = colour.get(nxt, WHITE)
            if state == BLACK:
                continue
            if state == GREY:
                path = [entry[0] for entry in stack]
                cycle = path[path.index(nxt):]
                cycle.reverse()
                raise CycleError(cycle)
            colour[nxt] = GREY
            stack.append((nxt, list(reversed(project.upstream(project[nxt])))))
    return order


def downstream(project: Project) -> dict[str, list[str]]:
    """For each task, the tasks that declare one of its outputs as an input."""
    found: dict[str, list[str]] = {name: [] for name in project.tasks}
    for task in project.tasks.values():
        for producer in project.upstream(task):
            found[producer].append(task.name)
    return found
