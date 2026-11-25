# taskgraph

A small incremental task runner, in the spirit of make, but driven by file contents
instead of timestamps. You describe tasks (what they read, what they write, a Python
function that does the work), and `build()` runs the ones whose results are out of date.

```python
from taskgraph import Builder, DiskFS, Project, Task, actions

project = Project()
project.add(Task("pp-main", actions.preprocess, inputs=["src/main.c"],
                 outputs=["build/main.c"], params={"search": ["include/local", "include"]}))
project.add(Task("bundle", actions.concat, inputs=["build/main.c", "README.txt"],
                 outputs=["dist/bundle.txt"], params={"separator": "\n"}))

result = Builder(project, DiskFS(".")).build()
result.ran          # ['pp-main', 'bundle'] the first time, [] the second
```

From the shell: put `project = Project()` and your tasks in a `Taskfile.py`, then
`python -m taskgraph build [TASK ...]`, `status`, `graph` or `clean`.

## Tasks

`Task(name, action, inputs=[], outputs=[...], params={}, version=1)`

- `inputs` are the files the task declares it reads. If one of them is another task's
  output, that task is *upstream*: it is brought up to date first.
- `outputs` are the files the task writes. Every output must be written by every
  successful run, and no two tasks may share an output.
- `params` are settings handed to the action (`ctx.params`).
- `version` is for you to bump when you change what the action's code does.

The *definition* of a task is its name, its action (the function's module and qualified
name), `version`, `inputs`, `outputs` and `params`.

The action is called with a `TaskContext`:

- `ctx.read(path)` returns the file's text, or `None` if there is no such file. A task may
  read any file this way, declared or not (a compiler reading the headers a source file
  includes, say), except another task's output that isn't one of its declared inputs.
- `ctx.write(path, text)` writes one of the task's outputs.
- `ctx.inputs`, `ctx.outputs`, `ctx.params` and `ctx.task` describe the task.

`taskgraph.actions` has a few ready-made actions: `copy`, `concat`, `strip_comments` and
`preprocess` (C-style `#include "name"`, looked up in `params["search"]`).

## What a build runs

`Builder(project, fs).build(targets=None)` builds the given task names and every task they
need through their inputs (all tasks if `targets` is None). It remembers what each task
read and wrote in `.taskgraph/state.json` on the same file system, so a new `Builder`, or
the next run of the shell, carries on where the last one stopped.

A task's *record* is what its last successful run read and wrote. What a run *read* is the
task's declared inputs, and every path the action passed to `ctx.read`, including paths
that turned out not to exist.

A task runs **exactly when** one of these is true, and otherwise it doesn't:

1. it has no record: it has never run successfully, or its last run failed;
2. its definition differs from the one recorded;
3. a file its last successful run read now has different content, or exists now and
   didn't then, or the other way round;
4. one of its outputs is missing, or no longer holds what the task last wrote there.

Only content counts: a file that was touched, rewritten with the same text, or put back
with an old timestamp is judged by what is in it. Only the last successful run counts: a
file the task read in some earlier run, but not in its last one, no longer matters.

Tasks are considered in dependency order, and a task is checked only after every task
upstream of it has been brought up to date in this same build. So an edit reaches the end
of a chain of tasks in one build; and when an upstream task runs again but writes exactly
what it wrote before, the tasks after it see unchanged inputs and don't run.

Projects can be big, with chains of thousands of tasks.

## Failures

A run fails if the action raises (`TaskFailed("message")` is the polite way), writes a
file that isn't one of its outputs, reads another task's output it didn't declare, or
returns without writing all its outputs. Then:

- the task is left with no record, so the next build runs it again, whatever changed or
  didn't; files it wrote before failing stay as they are;
- tasks that need it, directly or through other tasks, don't run in this build: they are
  *blocked* and keep their records;
- everything else in the build still runs.

## Cycles

If tasks need each other's outputs in a circle, `build()` raises `CycleError` before
running anything; its `cycle` attribute lists the tasks on the circle.

## Results and counters

`build()` returns a `BuildResult`: `ran` (task names in the order they ran, failures
included), `up_to_date`, `failed` (name to error message), `blocked`, and `ok`.
`builder.stats.executions` counts the actions a `Builder` has run, and `builder.log` lists
them.

## File systems

`DiskFS(root)` works on real files. `MemoryFS(files)` keeps text files in memory and is
what the tests use: `write(path, text, mtime=None)` (an explicit `mtime` is what `cp -p` or
unpacking an archive would leave), `touch(path)`, `delete(path)`, `read`, `exists`,
`mtime`, `files(prefix)` and `snapshot()`. Its clock is a counter that ticks on every
write.

## Tests

```
python -m pytest -q
```
