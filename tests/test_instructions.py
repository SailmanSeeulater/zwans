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


def test_a_project_set_up_for_other_agents_is_read_too(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use pnpm.", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("Never push.", encoding="utf-8")
    (tmp_path / "ZWANS.md").write_text("Prefer small diffs.", encoding="utf-8")

    found = load_instructions(tmp_path, tmp_path / "no-home")

    assert [path.name for path, _ in found] == ["AGENTS.md", "CLAUDE.md", "ZWANS.md"]


def test_an_import_line_brings_in_the_file_once(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use pnpm.", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "style.md").write_text("Two-space indents.", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text(
        "@AGENTS.md\n@docs/style.md\n@../outside.md\nAsk @maria about deploys.", encoding="utf-8"
    )
    (tmp_path.parent / "outside.md").write_text("secret", encoding="utf-8")

    found = load_instructions(tmp_path, tmp_path / "no-home")

    assert [text for _, text in found] == [
        "Use pnpm.",
        "Two-space indents.\n@../outside.md\nAsk @maria about deploys.",
    ]


def test_a_file_that_only_imports_another_adds_nothing(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Use pnpm.", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("@AGENTS.md", encoding="utf-8")
    (tmp_path / "ZWANS.md").symlink_to(tmp_path / "AGENTS.md")

    found = load_instructions(tmp_path, tmp_path / "no-home")

    assert [(path.name, text) for path, text in found] == [("AGENTS.md", "Use pnpm.")]


def test_the_system_prompt_includes_each_file(tmp_path: Path) -> None:
    path = tmp_path / "ZWANS.md"

    prompt = system_prompt(tmp_path, "bash", [(path, "Run tests with `make test`.")])

    assert f'<instructions file="{path}">\nRun tests with `make test`.\n</instructions>' in prompt
