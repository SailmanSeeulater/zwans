from pathlib import Path

import pytest

from kvstore import UnknownBackend, open_store
from kvstore.__main__ import main
from kvstore.jsonfile import JsonFileStore
from kvstore.memory import MemoryStore


def test_open_store_picks_the_backend(tmp_path: Path) -> None:
    assert isinstance(open_store("memory://"), MemoryStore)
    assert isinstance(open_store(f"json://{tmp_path / 'x.json'}"), JsonFileStore)


def test_unknown_backend() -> None:
    with pytest.raises(UnknownBackend):
        open_store("redis://localhost")


def test_not_a_url() -> None:
    with pytest.raises(ValueError):
        open_store("data.json")


def test_json_store_persists(tmp_path: Path) -> None:
    url = f"json://{tmp_path / 'x.json'}"
    with open_store(url) as store:
        store.set("a", "1")
    with open_store(url) as store:
        assert store.get("a") == "1"


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    url = f"json://{tmp_path / 'x.json'}"
    assert main(["--store", url, "set", "greeting", "hello"]) == 0
    assert main(["--store", url, "get", "greeting"]) == 0
    assert capsys.readouterr().out == "hello\n"
    assert main(["--store", url, "get", "missing"]) == 1
