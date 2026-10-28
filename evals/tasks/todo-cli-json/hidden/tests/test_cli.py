from pathlib import Path

import pytest

from todo.cli import main


def run(capsys: pytest.CaptureFixture[str], path: Path, *args: str) -> tuple[int, str]:
    code = main(["--file", str(path), *args])
    return code, capsys.readouterr().out


def test_add_then_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "todo.json"
    run(capsys, path, "add", "Buy milk")
    run(capsys, path, "add", "Walk the dog")

    code, out = run(capsys, path, "list")

    assert code == 0
    assert out == "[ ] 1 Buy milk\n[ ] 2 Walk the dog\n"


def test_done_marks_a_task(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "todo.json"
    run(capsys, path, "add", "Buy milk")
    run(capsys, path, "add", "Walk the dog")
    run(capsys, path, "done", "1")

    _, out = run(capsys, path, "list")
    assert out == "[x] 1 Buy milk\n[ ] 2 Walk the dog\n"

    _, out = run(capsys, path, "list", "--pending")
    assert out == "[ ] 2 Walk the dog\n"


def test_done_with_an_unknown_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run(capsys, tmp_path / "todo.json", "done", "7")
    assert code == 1
