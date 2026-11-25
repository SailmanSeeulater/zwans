"""The README's rules one at a time."""

import pytest
from oracle import Spec
from sample import SEARCH, compile_, docs, link, preprocess, strip
from test_incremental import project_of

from taskgraph import Builder, CycleError, MemoryFS, Project, Task, TaskFailed

FILES = {
    "src/main.c": '#include "util.h"\nint main = 1;\n// hello\n',
    "src/aux.c": "int aux = 2;\n",
    "include/util.h": '#include "base.h"\nint util = 3;\n',
    "include/base.h": "int base = 4;\n",
    "docs/intro.md": "Hi.\n",
}


def specs(opt: int = 1, version: int = 1, title: str = "T") -> list[Spec]:
    found = []
    for name in ("main", "aux"):
        found += [
            Spec(f"strip-{name}", strip, [f"src/{name}.c"], [f"build/{name}.s"],
                 {"marker": "//"}),
            Spec(f"pp-{name}", preprocess, [f"build/{name}.s"], [f"build/{name}.i"],
                 {"search": SEARCH}),
            Spec(f"cc-{name}", compile_, [f"build/{name}.i"], [f"build/{name}.o"],
                 {"opt": opt}, version),
        ]
    found.append(Spec("link", link, ["build/main.o", "build/aux.o"], ["bin/app"]))
    found.append(Spec("docs", docs, ["docs/intro.md"], ["build/docs.html"], {"title": title}))
    return found


ALL = {spec.name for spec in specs()}


def build(fs: MemoryFS, **options) -> set[str]:
    """Build everything with a fresh Builder, as a new process would; the tasks that ran."""
    result = Builder(project_of(specs(**options)), fs).build()
    assert result.ok, result.failed
    return set(result.ran)


@pytest.fixture
def fs() -> MemoryFS:
    files = MemoryFS(FILES)
    assert build(files) == ALL
    assert build(files) == set()
    return files


def test_touching_or_rewriting_a_file_unchanged_runs_nothing(fs: MemoryFS) -> None:
    fs.touch("src/main.c")
    fs.touch("include/base.h")
    fs.write("include/util.h", fs.read("include/util.h"))
    fs.touch("build/main.s")

    assert build(fs) == set()


def test_a_file_restored_with_an_old_mtime_still_counts_as_changed(fs: MemoryFS) -> None:
    fs.write("include/base.h", "int base = 5;\n", mtime=1)

    assert build(fs) == {"pp-main", "cc-main", "link"}
    assert "int base = 5;" in fs.read("build/main.i")


def test_a_change_reaches_the_end_in_one_build(fs: MemoryFS) -> None:
    fs.write("include/base.h", "int base = 40;\n")

    assert build(fs) == {"pp-main", "cc-main", "link"}
    assert build(fs) == set()


def test_identical_output_stops_the_rebuild(fs: MemoryFS) -> None:
    fs.write("src/main.c", fs.read("src/main.c") + "// another comment\n")
    assert build(fs) == {"strip-main"}

    fs.write("include/util.h", "int util = 3;\n#include \"base.h\"\n")  # same lines, sorted
    assert build(fs) == {"pp-main", "cc-main"}


def test_a_file_that_was_looked_for_and_missing_counts_when_it_appears(fs: MemoryFS) -> None:
    fs.write("include/local/base.h", "int base = 99;\n")
    assert build(fs) == {"pp-main", "cc-main", "link"}
    assert "int base = 99;" in fs.read("build/main.i")

    fs.delete("include/local/base.h")
    assert build(fs) == {"pp-main", "cc-main", "link"}

    fs.write("docs/footer.md", "bye\n")
    assert build(fs) == {"docs"}


def test_only_what_the_last_run_read_counts(fs: MemoryFS) -> None:
    fs.write("src/main.c", "int main = 1;\n")  # no longer includes util.h
    assert build(fs) == {"strip-main", "pp-main", "cc-main", "link"}

    fs.write("include/base.h", "int base = 0;\n")
    fs.write("include/util.h", "int util = 0;\n")
    assert build(fs) == set()


def test_a_changed_definition_reruns_the_task(fs: MemoryFS) -> None:
    assert build(fs, opt=2) == {"cc-main", "cc-aux", "link"}
    assert build(fs, opt=2, version=2) == {"cc-main", "cc-aux"}
    assert build(fs, opt=2, version=2, title="U") == {"docs"}


def test_an_output_changed_by_hand_is_rebuilt(fs: MemoryFS) -> None:
    fs.write("build/main.i", "junk\n")
    assert build(fs) == {"pp-main"}

    fs.delete("bin/app")
    assert build(fs) == {"link"}


def test_a_failed_task_leaves_no_record_and_blocks_only_what_needs_it(fs: MemoryFS) -> None:
    good = fs.read("src/main.c")
    fs.write("src/main.c", good + "#error broken\n")
    fs.write("src/aux.c", "int aux = 7;\n")
    project = project_of(specs())

    first = Builder(project, fs).build()
    assert set(first.ran) == {"strip-main", "pp-main", "strip-aux", "pp-aux", "cc-aux"}
    assert set(first.failed) == {"pp-main"}
    assert set(first.blocked) == {"cc-main", "link"}

    again = Builder(project, fs).build()  # nothing changed: the failed task runs again
    assert set(again.ran) == {"pp-main"} and set(again.failed) == {"pp-main"}
    assert set(again.blocked) == {"cc-main", "link"}

    fs.write("src/main.c", good)
    assert build(fs) == {"strip-main", "pp-main", "link"}  # cc-main's input is as it was


def test_a_task_that_fails_after_writing_runs_again() -> None:
    calls = []

    def flaky(ctx) -> None:
        calls.append(1)
        ctx.write("out.txt", ctx.read("in.txt") or "")
        if len(calls) == 1:
            raise RuntimeError("disk full")

    fs = MemoryFS({"in.txt": "a\n"})
    project = Project()
    project.add(Task("flaky", flaky, ["in.txt"], ["out.txt"]))
    project.add(Task("copy", strip, ["out.txt"], ["copy.txt"], {"marker": "//"}))

    first = Builder(project, fs).build()
    assert set(first.failed) == {"flaky"} and first.blocked == ["copy"]
    second = Builder(project, fs).build()
    assert set(second.ran) == {"flaky", "copy"} and second.ok
    assert set(Builder(project, fs).build().ran) == set()


def test_reading_another_tasks_output_without_declaring_it_fails() -> None:
    def sneaky(ctx) -> None:
        ctx.write("b.txt", ctx.read("a.txt") or "")

    fs = MemoryFS({"src.txt": "x\n"})
    project = Project()
    project.add(Task("make-a", strip, ["src.txt"], ["a.txt"], {"marker": "//"}))
    project.add(Task("make-b", sneaky, [], ["b.txt"]))

    result = Builder(project, fs).build()
    assert set(result.failed) == {"make-b"}


def test_a_task_that_doesnt_write_an_output_fails() -> None:
    fs = MemoryFS({"in.txt": "x\n"})
    project = Project()
    project.add(Task("lazy", lambda ctx: None, ["in.txt"], ["out.txt"]))

    assert set(Builder(project, fs).build().failed) == {"lazy"}


def test_building_a_target_builds_what_it_needs_only(fs: MemoryFS) -> None:
    fs.write("src/main.c", "int main = 2;\n")
    fs.write("src/aux.c", "int aux = 9;\n")
    result = Builder(project_of(specs()), fs).build(["cc-aux"])

    assert set(result.ran) == {"strip-aux", "pp-aux", "cc-aux"}
    assert build(fs) == {"strip-main", "pp-main", "cc-main", "link"}


@pytest.mark.parametrize("length", [2, 3, 6])
def test_a_cycle_is_reported_before_anything_runs(length: int) -> None:
    fs = MemoryFS({"seed.txt": "s\n"})
    project = Project()
    project.add(Task("before", strip, ["seed.txt"], ["before.txt"], {"marker": "//"}))
    names = [f"step{n}" for n in range(length)]
    for n, name in enumerate(names):
        upstream = f"out{(n - 1) % length}.txt"
        project.add(Task(name, link, [upstream, "before.txt"], [f"out{n}.txt"]))
    project.add(Task("after", link, ["out0.txt"], ["after.txt"]))
    builder = Builder(project, fs)

    with pytest.raises(CycleError) as caught:
        builder.build()

    assert set(caught.value.cycle) == set(names)
    assert builder.stats.executions == 0
    assert not fs.exists("before.txt")


def chain(length: int, seed: str) -> tuple[Project, MemoryFS]:
    def step(ctx) -> None:
        text = ctx.read(ctx.inputs[0])
        if text is None:
            raise TaskFailed("missing")
        ctx.write(ctx.outputs[0], text.upper() if ctx.params["upper"] else text)

    project = Project()
    for n in range(length):
        source = "seed.txt" if n == 0 else f"f{n - 1}.txt"
        project.add(Task(f"t{n}", step, [source], [f"f{n}.txt"], {"upper": n == 0}))
    return project, MemoryFS({"seed.txt": seed})


def test_a_long_chain_of_tasks() -> None:
    length = 3000
    project, fs = chain(length, "abc\n")

    first = Builder(project, fs).build([f"t{length - 1}"])
    assert len(first.ran) == length and fs.read(f"f{length - 1}.txt") == "ABC\n"
    assert Builder(project, fs).build().ran == []

    fs.write("seed.txt", "ABC\n")  # the first task gives the same output
    assert Builder(project, fs).build().ran == ["t0"]

    fs.write("seed.txt", "xyz\n")
    assert len(Builder(project, fs).build().ran) == length
    assert fs.read(f"f{length - 1}.txt") == "XYZ\n"
