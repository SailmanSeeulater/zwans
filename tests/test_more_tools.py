"""RunTests, Outline, References, Rename, ShowChanges, Docs, Memory, Python and AskUser."""

import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from helpers import needs_bash, needs_rg

from zwans.checkpoints import Checkpoints
from zwans.cli import approval
from zwans.cli.diffs import show_diff
from zwans.config import Config
from zwans.executor.local import LocalExecutor
from zwans.executor.seatbelt import SANDBOX_EXEC, SeatbeltExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Mode, Policy, PolicyFile
from zwans.prompt import system_prompt
from zwans.providers.fake import FakeProvider
from zwans.runtime import open_session
from zwans.tools.ask_user import AskUserInput, AskUserTool
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.docs import DocsInput, DocsTool
from zwans.tools.hints import says_missing
from zwans.tools.memory import MemoryInput, MemoryTool, read_notes
from zwans.tools.outline import OutlineInput, OutlineTool, outline
from zwans.tools.python_session import PythonInput, PythonTool
from zwans.tools.refs import ReferencesInput, ReferencesTool, RenameInput, RenameTool, positions
from zwans.tools.run_tests import RunTestsInput, RunTestsTool, find_runs
from zwans.tools.show_changes import ShowChangesInput, ShowChangesTool

on_a_mac = pytest.mark.skipif(
    sys.platform != "darwin" or not os.access(SANDBOX_EXEC, os.X_OK),
    reason="Seatbelt is part of macOS",
)
PYTEST = "python -m pytest -q --tb=short -p no:cacheprovider"


def permissions(
    tmp_path: Path, mode: Mode, *, allow: Sequence[str] = (), deny: Sequence[str] = ()
) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(mode=mode, allow=list(allow), deny=list(deny)), "test")
    executor = LocalExecutor(tmp_path)
    return Permissions(policy, lambda path: True, executor.relative, root=executor.root)


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")


def test_the_terminal_names_each_file_in_a_diff_of_several(
    capsys: pytest.CaptureFixture[str],
) -> None:
    one = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
    other = "--- a/pkg/b.py\n+++ b/pkg/b.py\n@@ -1 +1 @@\n-p\n+q\n"

    show_diff(one + other)
    several = [line.strip() for line in capsys.readouterr().out.splitlines()]
    show_diff(one)
    single = [line.strip() for line in capsys.readouterr().out.splitlines()]

    assert several == [
        "== a.py", "@@ -1 +1 @@", "-x", "+y", "== pkg/b.py", "@@ -1 +1 @@", "-p", "+q",
    ]  # fmt: skip
    assert single == ["@@ -1 +1 @@", "-x", "+y"]  # the call line already names the file


# -- RunTests


def test_the_test_runners_are_found_from_the_projects_files(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "tests/test_calc.py": "def test_ok(): pass\n",
            "web/package.json": '{"scripts": {"test": "vitest run"}}',
            "tools/package.json": '{"scripts": {"test": "node check.js && echo ok"}}',
            "none/package.json": '{"scripts": {"test": "echo no test specified && exit 1"}}',
            "core/Cargo.toml": "[package]\n",
        },
    )

    assert [(run.name, run.command) for run in find_runs(tmp_path)] == [
        ("pytest", PYTEST),
        ("cargo test in core", "cd core && cargo test --quiet"),
        ("npm test in tools", "cd tools && npm test --silent"),  # a script a shell must run
        ("vitest in web", "cd web && node_modules/.bin/vitest run"),
    ]
    # Paths and a filter narrow it to one runner and a few tests.
    narrowed = find_runs(tmp_path, ["tests/test_calc.py"], "slow and not net")
    assert [run.command for run in narrowed] == [
        f"{PYTEST} tests/test_calc.py -k 'slow and not net'"
    ]
    assert [run.command for run in find_runs(tmp_path, ["web/src/a.test.ts"], "adds")] == [
        "cd web && node_modules/.bin/vitest run src/a.test.ts -t adds"
    ]


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_run_tests_reports_the_failure_and_then_the_pass(tmp_path: Path, ctx: ToolContext) -> None:
    write(
        tmp_path,
        {
            "calc.py": "def double(n):\n    return n + n + 1\n",
            "test_calc.py": "from calc import double\n\n\n"
            "def test_double():\n    assert double(2) == 4\n",
        },
    )
    tool = RunTestsTool(tmp_path)

    failing = asyncio.run(tool.run(RunTestsInput(), ctx))
    (tmp_path / "calc.py").write_text("def double(n):\n    return n + n\n", encoding="utf-8")
    passing = asyncio.run(tool.run(RunTestsInput(paths=["test_calc.py"]), ctx))

    assert failing.content.startswith("Tests failed.\n\n## pytest failed (`")
    assert "assert 5 == 4" in failing.content and failing.is_error is False
    assert passing.content.splitlines()[0] == "All tests passed."
    assert "1 passed" in passing.content


@needs_bash
def test_run_tests_with_your_own_commands_or_none(tmp_path: Path, ctx: ToolContext) -> None:
    own = asyncio.run(
        RunTestsTool(tmp_path, ["true", "surely-not-installed-zz"]).run(RunTestsInput(), ctx)
    )

    assert own.content == (
        "All tests passed.\ntrue: passed\n\n"
        "surely-not-installed-zz isn't installed here, so it wasn't run."
    )
    with pytest.raises(ToolError, match="No test runner is set up"):
        asyncio.run(RunTestsTool(tmp_path).run(RunTestsInput(), ctx))


def test_the_policy_judges_run_tests_by_its_commands(tmp_path: Path) -> None:
    write(tmp_path, {"test_a.py": "def test_a(): pass\n"})
    tool = RunTestsTool(tmp_path)

    assert permissions(tmp_path, "auto").check(tool, {}).decision == Decision.ALLOW
    asked = permissions(tmp_path, "ask").check(tool, {"filter": "a"})
    assert (asked.decision, asked.rules) == (Decision.ASK, (f"Bash({PYTEST} -k a)",))
    assert permissions(tmp_path, "read-only").check(tool, {}).decision == Decision.DENY


# -- Outline

PYTHON_SOURCE = """import os


def total(values: list[int], *, start: int = 0) -> int:
    return sum(values, start)


class Report(Base):
    title = "x"

    async def render(self, width=80):
        def helper():
            pass
        return ""
"""


def test_outline_of_python_has_exact_signatures() -> None:
    assert outline("report.py", PYTHON_SOURCE) == [
        "     4  def total(values: list[int], *, start: int=0) -> int",
        "     8  class Report(Base)",
        "    11    async def render(self, width=80)",
    ]
    # Python that doesn't parse is still outlined, line by line.
    assert outline("broken.py", "def ok(:\n    pass\nclass K:\n") == [
        "     1  def ok(:",
        "     3  class K:",
    ]


def test_outline_of_other_languages_matches_declarations() -> None:
    script = (
        "import x from 'y';\n"
        "export async function load(id: string) {\n"
        "export const add = (a: number, b: number) => a + b;\n"
        "const limit = 5;\n"
        "export interface Row {\n"
        "class Store extends Base {\n"
    )

    assert outline("store.ts", script) == [
        "     2  export async function load(id: string)",
        "     3  export const add = (a: number, b: number) => a + b;",
        "     5  export interface Row",
        "     6  class Store extends Base",
    ]
    assert outline("main.go", "package main\n\nfunc (s *Server) Run() error {\n") == [
        "     3  func (s *Server) Run() error"
    ]
    assert outline("notes.md", "# Title\n") == []


@needs_rg
def test_outline_of_a_folder_lists_each_files_declarations(
    tmp_path: Path, ctx: ToolContext
) -> None:
    write(
        tmp_path,
        {
            "src/calc.py": "def total(values):\n    return sum(values)\n",
            "src/empty.py": "X = 1\n",
            "src/app.ts": "export function start() {\n}\n",
            "node_modules/pkg/index.js": "function hidden() {}\n",
            "README.md": "# Readme\n",
        },
    )
    tool = OutlineTool()

    folder = asyncio.run(tool.run(OutlineInput(path="."), ctx))
    one = asyncio.run(tool.run(OutlineInput(path="src/calc.py"), ctx))
    plain = asyncio.run(tool.run(OutlineInput(path="README.md"), ctx))

    assert folder.content.splitlines() == [
        "src/app.ts",
        "     1  export function start()",
        "src/calc.py",
        "     1  def total(values)",
    ]
    assert one.content == "src/calc.py\n     1  def total(values)"
    assert plain.content == "README.md defines nothing Outline recognises."


# -- References and Rename

CALC = "def total(values):\n    return sum(values)\n"
REPORT = (
    "from calc import total\n\n\n"
    "def report(values):\n"
    "    # total of the values\n"
    '    return f"total: {total(values)}"  # "total" stays in the text\n'
)


def test_python_names_are_found_by_token_not_by_text() -> None:
    assert positions("report.py", REPORT, "total") == [(1, 17), (6, 21)]
    assert positions("report.py", "subtotal = total_cost\n", "total") == []
    # Other languages are matched as whole words, strings and comments included.
    assert positions("app.js", 'const total = 1; // total\nsubtotal("total")\n', "total") == [
        (1, 6),
        (1, 20),
        (2, 10),
    ]


@needs_rg
def test_references_and_rename_cover_every_file(tmp_path: Path, ctx: ToolContext) -> None:
    write(tmp_path, {"calc.py": CALC, "pkg/report.py": REPORT, "notes.txt": "the total is 3\n"})

    found = asyncio.run(ReferencesTool().run(ReferencesInput(symbol="total"), ctx))
    tool = RenameTool(tmp_path)
    args = RenameInput(old="total", new="sum_values", path=".")
    preview = asyncio.run(tool.preview(args, ctx))
    assert (tmp_path / "calc.py").read_text("utf-8") == CALC  # a preview writes nothing
    renamed = asyncio.run(tool.run(args, ctx))

    assert found.content.splitlines() == [
        "calc.py:1: def total(values):",
        "notes.txt:1: the total is 3",
        "pkg/report.py:1: from calc import total",
        'pkg/report.py:6: return f"total: {total(values)}"  # "total" stays in the text',
    ]
    assert renamed.content == (
        "Renamed total to sum_values in 4 places across 3 files: "
        "calc.py (1), notes.txt (1), pkg/report.py (2)."
    )
    assert renamed.diff == preview and "+def sum_values(values):" in preview
    assert (tmp_path / "pkg" / "report.py").read_text("utf-8") == (
        "from calc import sum_values\n\n\n"
        "def report(values):\n"
        "    # total of the values\n"
        '    return f"total: {sum_values(values)}"  # "total" stays in the text\n'
    )


def test_a_missing_path_is_recognised_as_each_system_words_it() -> None:
    assert says_missing("rg: tests: No such file or directory (os error 2)")
    assert says_missing(
        "rg: tests: IO error for operation on tests: The system cannot find the file "
        "specified. (os error 2)"
    )
    assert says_missing("rg: a\\b: The system cannot find the path specified. (os error 3)")
    assert not says_missing("rg: regex parse error: unclosed group")


@needs_rg
def test_rename_refuses_what_isnt_a_name_or_isnt_there(tmp_path: Path, ctx: ToolContext) -> None:
    write(tmp_path, {"calc.py": CALC})
    tool = RenameTool(tmp_path)

    with pytest.raises(ToolError, match="isn't an identifier"):
        asyncio.run(tool.run(RenameInput(old="total", new="sum values"), ctx))
    with pytest.raises(ToolError, match="No uses of missing found"):
        asyncio.run(tool.run(RenameInput(old="missing", new="found"), ctx))
    with pytest.raises(ToolError, match="the same name"):
        asyncio.run(tool.run(RenameInput(old="total", new="total"), ctx))
    # A path that isn't there is said plainly, by all three tools that search.
    with pytest.raises(ToolError, match="no file or folder called 'folder'"):
        asyncio.run(tool.run(RenameInput(old="total", new="x", path="folder"), ctx))
    with pytest.raises(ToolError, match="no file or folder called 'folder'"):
        asyncio.run(OutlineTool().run(OutlineInput(path="folder"), ctx))
    with pytest.raises(ToolError, match="no file or folder called 'folder'"):
        asyncio.run(ReferencesTool().run(ReferencesInput(symbol="total", path="folder"), ctx))


@needs_rg
def test_the_policy_judges_a_rename_by_the_files_it_would_change(tmp_path: Path) -> None:
    write(tmp_path, {"calc.py": CALC, "pkg/report.py": REPORT, "other.py": "x = 1\n"})
    tool = RenameTool(tmp_path)
    args = {"old": "total", "new": "sum_values"}

    assert tool.edited_paths(args) == ["calc.py", "pkg/report.py"]
    assert permissions(tmp_path, "auto").check(tool, args).decision == Decision.ALLOW
    asked = permissions(tmp_path, "ask").check(tool, args)
    assert (asked.decision, asked.rules) == (
        Decision.ASK,
        ("Rename(calc.py)", "Rename(pkg/report.py)"),
    )
    # A rule written for Edit covers it, file by file.
    denied = permissions(tmp_path, "auto", deny=["Edit(pkg/**)"]).check(tool, args)
    assert denied.decision == Decision.DENY
    # And one about reading covers the two tools that only look.
    hidden = permissions(tmp_path, "auto", deny=["Read(pkg/**)"])
    assert hidden.check(ReferencesTool(), {"path": "pkg"}).decision == Decision.DENY
    assert hidden.check(OutlineTool(), {"path": "pkg/report.py"}).decision == Decision.DENY
    assert hidden.check(OutlineTool(), {"path": "calc.py"}).decision == Decision.ALLOW


# -- ShowChanges


def test_show_changes_is_everything_since_the_session_began(
    tmp_path: Path, ctx: ToolContext
) -> None:
    workspace = ctx.executor.root  # type: ignore[attr-defined]
    write(workspace, {"keep.py": "a = 1\n", "gone.py": "b = 2\n"})
    checkpoints = Checkpoints(workspace, tmp_path.parent / f"{tmp_path.name}-home", "s1")
    tool = ShowChangesTool(checkpoints)
    asyncio.run(checkpoints.save(1))

    untouched = asyncio.run(tool.run(ShowChangesInput(), ctx))
    write(workspace, {"keep.py": "a = 10\n", "new.py": "c = 3\n"})
    (workspace / "gone.py").unlink()
    asyncio.run(checkpoints.save(2))  # a later turn's checkpoint doesn't move the start
    changed = asyncio.run(tool.run(ShowChangesInput(), ctx))
    names = asyncio.run(tool.run(ShowChangesInput(names_only=True), ctx))

    assert untouched.content == "Nothing in the workspace has changed since this session began."
    assert names.content == (
        "3 files changed since this session began:\n"
        "deleted gone.py\nchanged keep.py\nadded   new.py"
    )
    assert changed.content.startswith(names.content + "\n\ndiff --git")
    diff = changed.content.replace("\r\n", "\n")  # write_text writes \r\n on Windows
    assert "-a = 1\n+a = 10" in diff and "+c = 3" in diff


def test_show_changes_says_so_without_checkpoints(ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match="Checkpoints are off"):
        asyncio.run(ShowChangesTool(None).run(ShowChangesInput(), ctx))


# -- Docs


@needs_bash
@pytest.mark.usefixtures("python_on_path")
def test_docs_come_from_the_installed_python(ctx: ToolContext) -> None:
    tool = DocsTool()

    found = asyncio.run(tool.run(DocsInput(name=" json.dumps "), ctx))

    assert "dumps(obj, *, skipkeys=False" in found.content
    with pytest.raises(ToolError, match=r"Nothing found for json\.nope"):
        asyncio.run(tool.run(DocsInput(name="json.nope"), ctx))
    with pytest.raises(ToolError, match="isn't a dotted name"):
        asyncio.run(tool.run(DocsInput(name="json; rm -rf ~"), ctx))


def test_the_policy_judges_docs_as_running_python(tmp_path: Path) -> None:
    tool = DocsTool()

    assert tool.commands({"name": "json.dumps"}) == ["python -m pydoc json.dumps"]
    assert tool.commands({"name": "json; rm -rf ~"}) == []  # the call fails before it runs
    assert permissions(tmp_path, "ask").check(tool, {"name": "json"}).decision == Decision.ASK
    assert permissions(tmp_path, "auto").check(tool, {"name": "json"}).decision == Decision.ALLOW


# -- Memory


def test_memory_keeps_notes_for_the_next_session(tmp_path: Path, ctx: ToolContext) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    workspace.mkdir()
    tool = MemoryTool(home, workspace)

    def call(action: Any, text: str) -> ToolOutput:
        return asyncio.run(tool.run(MemoryInput(action=action, text=text), ctx))

    call("add", "Run the tests with  `make check`,\nnot pytest.")
    kept = call("add", "The api/ folder is generated.")
    again = call("add", "The api/ folder is generated.")
    with pytest.raises(ToolError, match="2 notes contain 'the'"):
        call("remove", "the")
    removed = call("remove", "generated")

    assert kept.content == (
        "Kept.\n\nThe notes for this project:\n"
        "- Run the tests with `make check`, not pytest.\n- The api/ folder is generated."
    )
    assert again.content.startswith("That note is already kept.")
    assert removed.content.endswith("- Run the tests with `make check`, not pytest.")
    assert read_notes(home, workspace) == ["Run the tests with `make check`, not pytest."]
    assert read_notes(home, tmp_path / "elsewhere") == []  # each workspace has its own
    assert not list(workspace.iterdir())  # nothing is written into the project


def test_a_new_session_starts_with_the_notes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = Config(home=tmp_path / "home", subagents=False)
    ctx = ToolContext(executor=LocalExecutor(workspace))
    note = MemoryInput(action="add", text="Run the tests with make check.")
    asyncio.run(MemoryTool(config.home, workspace).run(note, ctx))

    opened = open_session(
        config, {}, workspace=workspace, make_provider=lambda c, m: FakeProvider([])
    )
    asyncio.run(opened.close())

    assert "Notes you kept about this project" in opened.info.system
    assert "- Run the tests with make check." in opened.info.system
    assert "Notes you kept" not in system_prompt(workspace, "bash", [])


def test_the_policy_judges_a_note_like_a_change_to_a_file(tmp_path: Path) -> None:
    tool = MemoryTool(tmp_path / "home", tmp_path)
    note = {"action": "add", "text": "x"}

    assert permissions(tmp_path, "auto").check(tool, note).decision == Decision.ALLOW
    assert permissions(tmp_path, "ask").check(tool, note).decision == Decision.ASK
    assert permissions(tmp_path, "read-only").check(tool, note).decision == Decision.DENY
    # After a page or a file has been read, a note is held to the rule for writes: what
    # was read mustn't be able to leave instructions for next time.
    tainted = permissions(tmp_path, "auto")
    tainted.tainted = True
    assert tainted.check(tool, note).decision == tainted.policy.after_untrusted.write


# -- Python


def python(tool: PythonTool, ctx: ToolContext, code: str, **more: Any) -> ToolOutput:
    return asyncio.run(tool.run(PythonInput(code=code, **more), ctx))


@pytest.mark.usefixtures("python_on_path")
def test_a_python_session_keeps_its_state_between_calls(ctx: ToolContext) -> None:
    tool = PythonTool()

    async def session() -> list[ToolOutput]:
        try:
            return [
                await tool.run(PythonInput(code="import math\nn = 20\nprint('set')"), ctx),
                await tool.run(PythonInput(code="math.factorial(n) // 10**10"), ctx),
                await tool.run(PythonInput(code="n = n + 1"), ctx),
                await tool.run(PythonInput(code="1 / 0"), ctx),
                await tool.run(PythonInput(code="n"), ctx),
                await tool.run(PythonInput(code="'n' in globals()", restart=True), ctx),
            ]
        finally:
            await tool.aclose()

    first, value, quiet, failed, kept, fresh = asyncio.run(session())

    assert (first.content, value.content, quiet.content) == ("set", "243290200", "(no output)")
    assert failed.is_error and failed.content.endswith("ZeroDivisionError: division by zero")
    assert 'File "<session>", line 1' in failed.content  # its own frames, not the tool's
    assert (kept.content, fresh.content) == ("21", "False")


@pytest.mark.usefixtures("python_on_path")
def test_a_python_call_that_hangs_or_ends_the_interpreter(ctx: ToolContext) -> None:
    tool = PythonTool()

    async def session() -> list[ToolOutput]:
        try:
            return [
                await tool.run(PythonInput(code="x = 1"), ctx),
                await tool.run(PythonInput(code="import time; time.sleep(30)", timeout=1), ctx),
                await tool.run(PythonInput(code="'x' in globals()"), ctx),
                await tool.run(PythonInput(code="import os; os._exit(3)"), ctx),
                await tool.run(PythonInput(code="2 + 2"), ctx),
            ]
        finally:
            await tool.aclose()

    _, hung, after, ended, again = asyncio.run(session())

    assert hung.is_error and "Stopped after 1s" in hung.content
    assert after.content == "False"  # a fresh interpreter, as the message said
    assert ended.is_error and "session ended" in ended.content
    assert again.content == "4"


def test_the_policy_judges_python_as_running_code(tmp_path: Path) -> None:
    tool = PythonTool()

    assert tool.commands({"code": "print(1)"}) == ["python -c 'print(1)'"]
    assert permissions(tmp_path, "ask").check(tool, {"code": "x"}).decision == Decision.ASK
    assert permissions(tmp_path, "auto").check(tool, {"code": "x"}).decision == Decision.ALLOW
    assert permissions(tmp_path, "read-only").check(tool, {"code": "x"}).decision == Decision.DENY


@on_a_mac
@pytest.mark.usefixtures("python_on_path")
def test_in_a_sandbox_of_its_own_python_asks_nothing_and_reaches_nothing(tmp_path: Path) -> None:
    base = Path(__file__).resolve().parents[1] / ".pytest_cache" / f"py-{os.getpid()}"
    (base / "chat").mkdir(parents=True, exist_ok=True)
    tool = PythonTool(sandbox=SeatbeltExecutor(base / "chat"))
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    probe = (
        "import socket, pathlib\n"
        "def tried(what):\n"
        "    try:\n"
        "        what()\n"
        "        return 'did it'\n"
        "    except OSError as error:\n"
        "        return 'refused'\n"
        f"outside = pathlib.Path({str(base / 'escaped.txt')!r})\n"
        "[tried(lambda: socket.create_connection(('1.1.1.1', 443), timeout=5)),\n"
        " tried(lambda: outside.write_text('x')),\n"
        " tried(lambda: pathlib.Path('inside.txt').write_text('x'))]"
    )

    async def session() -> ToolOutput:
        try:
            return await tool.run(PythonInput(code=probe), ctx)
        finally:
            await tool.aclose()

    try:
        result = asyncio.run(session())
        assert result.content == "['refused', 'refused', 'did it']"
        assert not (base / "escaped.txt").exists()
    finally:
        import shutil

        shutil.rmtree(base, ignore_errors=True)
    assert tool.read_only is True and tool.commands({"code": "x"}) == []
    assert permissions(tmp_path, "ask").check(tool, {"code": "x"}).decision == Decision.ALLOW


# -- AskUser


def test_ask_user_returns_the_answer_or_says_nobody_is_there(tmp_path: Path) -> None:
    asked: list[tuple[str, list[str]]] = []

    async def answer(question: str, options: Sequence[str]) -> str | None:
        asked.append((question, list(options)))
        return " Keep both "

    async def silence(question: str, options: Sequence[str]) -> str | None:
        return None

    tool = AskUserTool()
    executor = LocalExecutor(tmp_path)
    args = AskUserInput(question=" Delete the old tests? ", options=["Keep  both", "Delete", " "])

    answered = asyncio.run(tool.run(args, ToolContext(executor=executor, ask=answer)))
    nobody = asyncio.run(tool.run(args, ToolContext(executor=executor)))
    unanswered = asyncio.run(tool.run(args, ToolContext(executor=executor, ask=silence)))

    assert answered.content == "The user answered: Keep both"
    assert asked == [("Delete the old tests?", ["Keep both", "Delete"])]
    assert nobody.is_error and nobody.content.startswith("Nobody is here to answer")
    assert unanswered.is_error


def test_the_terminal_takes_a_number_or_your_own_words(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    typed = iter(["2", " Neither, use black ", "9", ""])
    monkeypatch.setattr(approval, "_prompt", lambda text: next(typed))
    options = ["Spaces", "Tabs"]

    answers = [approval.terminal_question("Tabs or spaces?", options) for _ in range(4)]

    # A number picks an option; anything else, an out-of-range number too, is the answer.
    assert answers == ["Tabs", "Neither, use black", "9", None]
    shown = capsys.readouterr().out
    assert "? Tabs or spaces?" in shown and "1. Spaces" in shown and "2. Tabs" in shown


def test_ask_user_is_offered_only_when_someone_can_be_asked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config = Config(home=tmp_path / "home", subagents=False)

    async def answer(question: str, options: Sequence[str]) -> str | None:
        return "yes"

    def names(**how: Any) -> list[str]:
        opened = open_session(
            config, {}, workspace=workspace, make_provider=lambda c, m: FakeProvider([]), **how
        )
        try:
            return [tool.name for tool in opened.session.tools]
        finally:
            asyncio.run(opened.close())

    assert "AskUser" not in names()  # an eval, or `zwans run` with nobody watching
    assert "AskUser" in names(asker=answer)
    assert "AskUser" in names(ask_later=True)
