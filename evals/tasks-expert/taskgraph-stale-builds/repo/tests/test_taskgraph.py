import pytest

from taskgraph import Builder, MemoryFS, Project, ProjectError, Task, TaskFailed, actions
from taskgraph.cli import main


def site() -> tuple[Project, MemoryFS]:
    fs = MemoryFS(
        {
            "pages/index.txt": '# home page\n#include "header.txt"\nWelcome.\n',
            "parts/header.txt": "My Site\n",
            "notes.txt": "draft\n",
        }
    )
    project = Project()
    project.add(Task("index", actions.preprocess, ["pages/index.txt"], ["out/index.txt"],
                     {"search": ["parts"]}))
    project.add(Task("clean-index", actions.strip_comments, ["out/index.txt"],
                     ["out/index.clean.txt"]))
    project.add(Task("notes", actions.copy, ["notes.txt"], ["out/notes.txt"]))
    return project, fs


def test_first_build_runs_everything_and_second_nothing() -> None:
    project, fs = site()

    first = Builder(project, fs).build()
    assert sorted(first.ran) == ["clean-index", "index", "notes"]
    assert first.ok
    assert fs.read("out/index.clean.txt") == "My Site\nWelcome.\n"

    second = Builder(project, fs).build()
    assert second.ran == []
    assert sorted(second.up_to_date) == ["clean-index", "index", "notes"]


def test_upstream_tasks_run_first() -> None:
    project, fs = site()
    result = Builder(project, fs).build()

    assert result.ran.index("index") < result.ran.index("clean-index")


def test_an_edited_input_reruns_its_task() -> None:
    project, fs = site()
    Builder(project, fs).build()

    fs.write("notes.txt", "final\n")
    result = Builder(project, fs).build()

    assert result.ran == ["notes"]
    assert fs.read("out/notes.txt") == "final\n"


def test_targets_build_only_what_they_need() -> None:
    project, fs = site()

    result = Builder(project, fs).build(["clean-index"])

    assert result.ran == ["index", "clean-index"]
    assert not fs.exists("out/notes.txt")


def test_a_failing_task_is_reported() -> None:
    def broken(ctx) -> None:
        raise TaskFailed("no way")

    fs = MemoryFS({"a.txt": "a"})
    project = Project()
    project.add(Task("broken", broken, ["a.txt"], ["b.txt"]))
    project.add(Task("after", actions.copy, ["b.txt"], ["c.txt"]))
    project.add(Task("other", actions.copy, ["a.txt"], ["d.txt"]))

    result = Builder(project, fs).build()

    assert result.failed == {"broken": "no way"}
    assert result.blocked == ["after"]
    assert fs.read("d.txt") == "a"
    assert not result.ok


def test_a_task_may_only_write_its_outputs() -> None:
    def stray(ctx) -> None:
        ctx.write("elsewhere.txt", "x")

    project = Project()
    project.add(Task("stray", stray, [], ["out.txt"]))
    result = Builder(project, MemoryFS()).build()

    assert "not one of its outputs" in result.failed["stray"]


def test_project_errors() -> None:
    project = Project()
    project.add(Task("a", actions.copy, ["x"], ["y"]))
    with pytest.raises(ProjectError):
        project.add(Task("b", actions.copy, ["x"], ["y"]))
    with pytest.raises(ProjectError):
        project.add(Task("a", actions.copy, ["x"], ["z"]))
    with pytest.raises(ProjectError):
        Task("c", actions.copy, ["x"], [])
    with pytest.raises(ProjectError):
        Builder(project, MemoryFS()).build(["nope"])


def test_the_decorator_form() -> None:
    project = Project()

    @project.task(inputs=["in.txt"], outputs=["out.txt"], params={"suffix": "!"})
    def shout(ctx) -> None:
        ctx.write("out.txt", (ctx.read("in.txt") or "").upper() + ctx.params["suffix"])

    fs = MemoryFS({"in.txt": "hi"})
    assert Builder(project, fs).build().ran == ["shout"]
    assert fs.read("out.txt") == "HI!"


def test_the_shell(tmp_path, capsys) -> None:
    (tmp_path / "src.txt").write_text("hello\n")
    (tmp_path / "Taskfile.py").write_text(
        "from taskgraph import Project, Task, actions\n"
        "project = Project()\n"
        "project.add(Task('copy', actions.copy, ['src.txt'], ['out/copy.txt']))\n"
    )
    taskfile = str(tmp_path / "Taskfile.py")

    assert main(["-f", taskfile, "build"]) == 0
    assert (tmp_path / "out" / "copy.txt").read_text() == "hello\n"
    assert main(["-f", taskfile, "status"]) == 0
    assert "copy: up to date" in capsys.readouterr().out
    assert main(["-f", taskfile, "clean"]) == 0
    assert not (tmp_path / "out" / "copy.txt").exists()
