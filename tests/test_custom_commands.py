from pathlib import Path

import pytest

from zwans.custom_commands import expand, load, parse


def write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text)
    return path


def test_a_file_with_a_header_becomes_a_command(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "fix-lint.md",
        "---\ndescription: Fix the lint\nargs: [path]\nloop: ruff check .\nrounds: 6\n---\n"
        "Fix what `ruff check $ARGUMENTS` reports.\n",
    )

    command = parse(path, "project")

    assert command.name == "fix-lint" and command.description == "Fix the lint"
    assert command.args == "[path]" and command.check == "ruff check ." and command.rounds == 6
    assert command.body == "Fix what `ruff check $ARGUMENTS` reports."


def test_without_a_header_the_first_line_describes_it(tmp_path: Path) -> None:
    command = parse(write(tmp_path, "explain.md", "# Explain this code\n\nIn plain words."), "user")

    assert command.description == "Explain this code" and command.check == ""


@pytest.mark.parametrize(
    ("name", "text", "why"),
    [
        ("Bad Name.md", "hi", "lowercase letters"),
        ("empty.md", "---\ndescription: x\n---\n\n", "no prompt"),
        ("odd.md", "---\nmodel: opus\n---\nhi", "the header takes"),
        ("many.md", "---\nrounds: 99\n---\nhi", "rounds is a number"),
    ],
)
def test_a_broken_file_says_what_is_wrong(tmp_path: Path, name: str, text: str, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        parse(write(tmp_path, name, text), "user")


def test_arguments_fill_the_placeholders_or_follow_the_text(tmp_path: Path) -> None:
    whole = parse(write(tmp_path, "a.md", "Review $ARGUMENTS carefully."), "user")
    words = parse(write(tmp_path, "b.md", "Move $1 to $2."), "user")
    plain = parse(write(tmp_path, "c.md", "Write tests."), "user")

    assert expand(whole, "src/app.py") == "Review src/app.py carefully."
    assert expand(words, '"old name.py" new.py') == "Move old name.py to new.py."
    assert expand(words, "only") == "Move only to ."
    assert expand(plain, "for the parser") == "Write tests.\n\nfor the parser"
    assert expand(plain, "") == "Write tests."


def test_the_project_wins_and_zwans_keeps_its_own_names(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "work"
    write(home / "commands", "review.md", "Mine.")
    write(home / "commands", "notes.md", "Notes.")
    write(workspace / ".zwans" / "commands", "review.md", "The project's.")
    write(workspace / ".zwans" / "commands", "loop.md", "Shadowing.")
    write(workspace / ".zwans" / "commands", "bad name.md", "Bad name.")

    found, problems = load(workspace, home)

    assert sorted(found) == ["notes", "review"]
    assert found["review"].body == "The project's." and found["review"].scope == "project"
    assert found["notes"].scope == "user"
    assert any("/loop is one of Zwans's own" in p for p in problems)
    assert any("bad name.md" in p for p in problems)


def test_a_projects_check_needs_trusting_and_yours_does_not(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = parse(write(tmp_path / "p", "t.md", "---\nloop: pytest\n---\nFix."), "project")
    mine = parse(write(tmp_path / "u", "t.md", "---\nloop: pytest\n---\nFix."), "user")
    words = parse(write(tmp_path / "w", "t.md", "Fix."), "project")

    assert project.needs_trust(home) and not mine.needs_trust(home)
    assert not words.needs_trust(home)  # no check, nothing runs
    project.trust(home)
    assert not project.needs_trust(home)
    project.path.write_text("---\nloop: rm -rf ~\n---\nFix.")
    assert parse(project.path, "project").needs_trust(home)  # changed, so asked again
