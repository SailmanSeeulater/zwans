from pathlib import Path

from zwans.context.instructions import load_instructions
from zwans.prompt import system_prompt


def test_user_instructions_come_before_the_projects(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    workspace.mkdir()
    (home / "ZWANS.md").write_text("Use British spelling.", encoding="utf-8")
    (workspace / "ZWANS.md").write_text("Run tests with `make test`.", encoding="utf-8")

    found = load_instructions(workspace, home)

    assert [text for _, text in found] == ["Use British spelling.", "Run tests with `make test`."]


def test_missing_or_empty_files_are_skipped(tmp_path: Path) -> None:
    (tmp_path / "ZWANS.md").write_text("  \n", encoding="utf-8")

    assert load_instructions(tmp_path, tmp_path / "no-home") == []


def test_the_system_prompt_includes_each_file(tmp_path: Path) -> None:
    path = tmp_path / "ZWANS.md"

    prompt = system_prompt(tmp_path, "bash", [(path, "Run tests with `make test`.")])

    assert f'<instructions file="{path}">\nRun tests with `make test`.\n</instructions>' in prompt
