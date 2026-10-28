import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo.cli import main


def run(capsys: pytest.CaptureFixture[str], path: Path, *args: str) -> tuple[int, str]:
    code = main(["--file", str(path), *args])
    return code, capsys.readouterr().out


def make_list(capsys: pytest.CaptureFixture[str], path: Path) -> None:
    run(capsys, path, "add", "Buy milk")
    run(capsys, path, "add", 'Read "Dune", again')
    run(capsys, path, "add", "Call Zoë")
    run(capsys, path, "done", "2")


def test_list_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "todo.json"
    make_list(capsys, path)

    code, out = run(capsys, path, "list", "--json")

    assert code == 0
    assert json.loads(out) == [
        {"id": 1, "title": "Buy milk", "done": False},
        {"id": 2, "title": 'Read "Dune", again', "done": True},
        {"id": 3, "title": "Call Zoë", "done": False},
    ]


def test_list_json_with_pending(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "todo.json"
    make_list(capsys, path)

    _, out = run(capsys, path, "list", "--pending", "--json")
    assert [task["id"] for task in json.loads(out)] == [1, 3]

    _, out = run(capsys, path, "list", "--json", "--pending")
    assert [task["id"] for task in json.loads(out)] == [1, 3]


def test_list_json_when_empty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, tmp_path / "todo.json", "list", "--json")

    assert code == 0
    assert json.loads(out) == []


def test_plain_list_is_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "todo.json"
    make_list(capsys, path)

    _, out = run(capsys, path, "list")

    assert out == '[ ] 1 Buy milk\n[x] 2 Read "Dune", again\n[ ] 3 Call Zoë\n'


def test_list_json_from_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "todo.json"
    make_list(capsys, path)
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "todo", "--file", str(path), "list", "--json"],
        cwd=root,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        check=True,
    )

    tasks = json.loads(result.stdout.decode("utf-8"))
    assert [task["done"] for task in tasks] == [False, True, False]
