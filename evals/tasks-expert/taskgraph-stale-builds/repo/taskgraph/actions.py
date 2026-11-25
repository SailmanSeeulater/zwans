"""Ready-made actions for common tasks.

    project.add(Task("app.c", actions.preprocess, inputs=["src/app.c"],
                     outputs=["build/app.c"], params={"search": ["include"]}))
"""

import re

from taskgraph.context import TaskContext
from taskgraph.project import TaskFailed

INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"\s*$')


def copy(ctx: TaskContext) -> None:
    """Copy the one input to the one output."""
    (source,) = ctx.inputs
    (target,) = ctx.outputs
    text = ctx.read(source)
    if text is None:
        raise TaskFailed(f"{source} does not exist")
    ctx.write(target, text)


def concat(ctx: TaskContext) -> None:
    """Join the inputs, in order, into the one output (params: "separator")."""
    (target,) = ctx.outputs
    parts = []
    for path in ctx.inputs:
        text = ctx.read(path)
        if text is None:
            raise TaskFailed(f"{path} does not exist")
        parts.append(text)
    ctx.write(target, ctx.params.get("separator", "").join(parts))


def strip_comments(ctx: TaskContext) -> None:
    """Copy the input without lines that start with the comment marker (params: "marker")."""
    (source,) = ctx.inputs
    (target,) = ctx.outputs
    marker = ctx.params.get("marker", "#")
    text = ctx.read(source)
    if text is None:
        raise TaskFailed(f"{source} does not exist")
    kept = [line for line in text.splitlines() if not line.lstrip().startswith(marker)]
    ctx.write(target, "\n".join(kept) + ("\n" if kept else ""))


def preprocess(ctx: TaskContext) -> None:
    """Inline `#include "name"` lines, C style.

    Each name is looked up in the directories of params["search"], in order; the first
    that has it wins. Included files may include others; a file already included is not
    included again.
    """
    (source,) = ctx.inputs
    (target,) = ctx.outputs
    search = list(ctx.params.get("search", []))
    text = ctx.read(source)
    if text is None:
        raise TaskFailed(f"{source} does not exist")
    done: set[str] = set()
    out: list[str] = []
    # An explicit stack of line iterators, so deep include chains don't recurse.
    stack = [iter(text.splitlines())]
    while stack:
        line = next(stack[-1], None)
        if line is None:
            stack.pop()
            continue
        match = INCLUDE.match(line)
        if not match:
            out.append(line)
            continue
        name = match.group(1)
        found = None
        for directory in search:
            path = f"{directory}/{name}" if directory else name
            content = ctx.read(path)
            if content is not None:
                found = (path, content)
                break
        if found is None:
            raise TaskFailed(f"{source}: cannot find {name}")
        path, content = found
        if path in done:
            continue
        done.add(path)
        stack.append(iter(content.splitlines()))
    ctx.write(target, "\n".join(out) + ("\n" if out else ""))
