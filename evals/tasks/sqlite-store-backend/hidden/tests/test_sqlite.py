import sqlite3
from pathlib import Path

import pytest

from kvstore import KeyNotFound, Store, open_store
from kvstore.__main__ import main
from kvstore.sqlite import SqliteStore


def test_factory_opens_sqlite(tmp_path: Path) -> None:
    with open_store(f"sqlite://{tmp_path / 'data.db'}") as store:
        assert isinstance(store, SqliteStore)
        assert isinstance(store, Store)


def test_constructor_takes_a_path(tmp_path: Path) -> None:
    store = SqliteStore(str(tmp_path / "direct.db"))
    try:
        store.set("a", "1")
        assert store.get("a") == "1"
    finally:
        store.close()


def test_data_survives_reopening(tmp_path: Path) -> None:
    url = f"sqlite://{tmp_path / 'data.db'}"
    with open_store(url) as store:
        store.set("kept", "yes")
        store.set("changed", "old")
        store.set("changed", "new")
        store.set("gone", "soon")
        store.delete("gone")

    with open_store(url) as store:
        assert store.get("kept") == "yes"
        assert store.get("changed") == "new"
        with pytest.raises(KeyNotFound):
            store.get("gone")
        assert store.keys() == ["changed", "kept"]


def test_it_is_a_real_sqlite_file(tmp_path: Path) -> None:
    path = tmp_path / "data.db"
    with open_store(f"sqlite://{path}") as store:
        store.set("a", "1")

    connection = sqlite3.connect(path)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        assert tables.fetchall()
    finally:
        connection.close()


def test_relative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with open_store("sqlite://relative.db") as store:
        store.set("a", "1")

    assert (tmp_path / "relative.db").is_file()


def test_in_memory() -> None:
    with open_store("sqlite://:memory:") as store:
        store.set("a", "1")
        assert store.get("a") == "1"
    with open_store("sqlite://:memory:") as store:
        assert store.keys() == []


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    url = f"sqlite://{tmp_path / 'cli.db'}"
    assert main(["--store", url, "set", "user.1", "ana"]) == 0
    assert main(["--store", url, "set", "user.2", "ben"]) == 0
    assert main(["--store", url, "set", "team", "red"]) == 0
    assert main(["--store", url, "del", "team"]) == 0
    capsys.readouterr()

    assert main(["--store", url, "keys", "user."]) == 0
    assert capsys.readouterr().out == "user.1\nuser.2\n"
    assert main(["--store", url, "get", "team"]) == 1


def test_readme_mentions_sqlite() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    assert "sqlite" in readme.read_text(encoding="utf-8").lower()
