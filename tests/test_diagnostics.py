import asyncio
import shutil
from collections.abc import Sequence
from pathlib import Path

import pytest
from helpers import needs_bash

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Mode, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.diagnostics import DiagnosticsInput, DiagnosticsTool, find_checks

RUFF = "ruff check --no-fix --output-format=concise"


def commands(root: Path, *paths: str) -> list[str]:
    return [check.command for check in find_checks(root, paths)]


def run(tool: DiagnosticsTool, ctx: ToolContext, *paths: str) -> ToolOutput:
    return asyncio.run(tool.run(DiagnosticsInput(paths=list(paths)), ctx))


def permissions(tmp_path: Path, mode: Mode, *, deny: Sequence[str] = ()) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(mode=mode, deny=list(deny)), "test")
    executor = LocalExecutor(tmp_path)
    return Permissions(policy, lambda path: True, executor.relative, root=executor.root)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A Python back end at the root and a TypeScript front end in web/, like Zwans itself."""
    (tmp_path / "pyproject.toml").write_text('[tool.mypy]\nfiles = ["src"]\n', encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "tsconfig.json").write_text("{}", encoding="utf-8")
    (web / "eslint.config.mjs").write_text("export default [];", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()  # other people's code: never looked in
    (tmp_path / "node_modules" / "tsconfig.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_the_checkers_are_found_from_the_projects_files(project: Path) -> None:
    assert [(c.name, c.command) for c in find_checks(project)] == [
        ("ruff", f"{RUFF} ."),
        ("mypy", "mypy"),  # its config says what to check
        ("tsc in web", "cd web && node_modules/.bin/tsc --noEmit -p ."),
        ("eslint in web", "cd web && node_modules/.bin/eslint ."),
    ]


def test_mypy_checks_everything_when_its_config_names_nothing(tmp_path: Path) -> None:
    (tmp_path / "mypy.ini").write_text("[mypy]\nstrict = True\n", encoding="utf-8")

    assert commands(tmp_path) == ["mypy ."]
    assert commands(tmp_path, "app.py") == ["mypy app.py"]


def test_paths_narrow_it_to_the_checkers_for_those_files(project: Path) -> None:
    assert commands(project, "src/app.py", "my file.py") == [
        f"{RUFF} src/app.py 'my file.py'",
        "mypy src/app.py 'my file.py'",
    ]
    # tsc can only check a whole project, so it does; eslint takes the file.
    assert commands(project, "web/src/page.tsx") == [
        "cd web && node_modules/.bin/tsc --noEmit -p .",
        "cd web && node_modules/.bin/eslint src/page.tsx",
    ]
    assert commands(project, "web") == [
        "cd web && node_modules/.bin/tsc --noEmit -p .",
        "cd web && node_modules/.bin/eslint .",
    ]
    assert commands(project, "README.md") == []


def test_other_languages_and_nothing_at_all(tmp_path: Path) -> None:
    assert find_checks(tmp_path) == []
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")

    assert commands(tmp_path) == ["cargo check --quiet --message-format=short", "go vet ./..."]


@needs_bash
def test_the_report_says_who_found_what(tmp_path: Path, ctx: ToolContext) -> None:
    own = ["echo 'a.py:1: error: boom'; exit 1", "true", "surely-not-installed-zz --check"]

    output = run(DiagnosticsTool(tmp_path, own), ctx)

    assert output.is_error is False  # findings are an answer, not a failure
    assert output.content.splitlines()[0] == "1 of 2 checkers found problems."
    assert "## echo (`echo 'a.py:1: error: boom'; exit 1`, exit code 1)" in output.content
    assert "a.py:1: error: boom" in output.content
    assert "No problems from: true." in output.content
    assert "Not installed here, so not run: surely-not-installed-zz." in output.content


@needs_bash
def test_a_clean_project_and_one_with_nothing_installed(tmp_path: Path, ctx: ToolContext) -> None:
    clean = run(DiagnosticsTool(tmp_path, ["true", "true"]), ctx)
    nothing = run(DiagnosticsTool(tmp_path, ["surely-not-installed-zz"]), ctx)

    assert (clean.content, clean.is_error) == ("No problems found by true, true.", False)
    assert nothing.is_error is True
    assert nothing.content == "Not installed here, so not run: surely-not-installed-zz."


def test_a_project_with_no_checker_says_so(tmp_path: Path, ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match="No checker is set up"):
        run(DiagnosticsTool(tmp_path), ctx)


@needs_bash
@pytest.mark.usefixtures("python_on_path")
@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_ruff_finds_an_unused_import(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("import os\n\nprint('hi')\n", encoding="utf-8")

    output = run(DiagnosticsTool(tmp_path), ctx, "app.py")

    assert "1 of 1 checker found problems." in output.content
    assert "F401" in output.content and "app.py:1" in output.content


def test_the_policy_judges_it_by_the_commands_it_would_run(project: Path) -> None:
    tool = DiagnosticsTool(project)

    # The checkers run code, so it's judged as Bash running them would be.
    assert permissions(project, "auto").check(tool, {}).decision == Decision.ALLOW
    asked = permissions(project, "ask").check(tool, {"paths": ["src/app.py"]})
    assert asked.decision == Decision.ASK
    assert "runs code" in asked.reason
    assert asked.rules == (f"Bash({RUFF} src/app.py)", "Bash(mypy src/app.py)")
    assert permissions(project, "read-only").check(tool, {}).decision == Decision.DENY

    # A rule about a command covers the same command here.
    denied = permissions(project, "auto", deny=["Bash(mypy*)"]).check(tool, {})
    assert denied.decision == Decision.DENY and "mypy" in denied.reason


def test_a_project_with_no_checker_asks_nothing(tmp_path: Path) -> None:
    verdict = permissions(tmp_path, "ask").check(DiagnosticsTool(tmp_path), {"paths": 3})

    assert verdict.decision == Decision.ALLOW  # it will only report that there's nothing to run
