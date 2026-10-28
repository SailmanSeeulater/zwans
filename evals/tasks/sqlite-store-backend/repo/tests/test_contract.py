"""Behaviour every backend must share."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from kvstore import KeyNotFound, Store, open_store

BACKENDS = ["memory", "json"]


def url_for(backend: str, folder: Path) -> str:
    if backend == "memory":
        return "memory://"
    return f"{backend}://{folder / ('store.' + backend)}"


@pytest.fixture(params=BACKENDS)
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Store]:
    with open_store(url_for(request.param, tmp_path)) as opened:
        yield opened


def test_set_and_get(store: Store) -> None:
    store.set("colour", "blue")
    assert store.get("colour") == "blue"


def test_set_replaces(store: Store) -> None:
    store.set("colour", "blue")
    store.set("colour", "green")
    assert store.get("colour") == "green"
    assert store.keys() == ["colour"]


def test_missing_keys(store: Store) -> None:
    with pytest.raises(KeyNotFound):
        store.get("nope")
    with pytest.raises(KeyNotFound):
        store.delete("nope")


def test_delete(store: Store) -> None:
    store.set("a", "1")
    store.delete("a")
    assert "a" not in store
    assert store.keys() == []


def test_keys_are_sorted_and_filtered(store: Store) -> None:
    for key in ["user.2", "user.10", "admin", "user.1"]:
        store.set(key, "x")

    assert store.keys() == ["admin", "user.1", "user.10", "user.2"]
    assert store.keys("user.") == ["user.1", "user.10", "user.2"]
    assert store.keys("nobody") == []


def test_odd_values(store: Store) -> None:
    store.set("empty", "")
    store.set("text", "naïve 🦆 'quotes' \"double\"\nnew line")

    assert store.get("empty") == ""
    assert store.get("text") == "naïve 🦆 'quotes' \"double\"\nnew line"
    assert "empty" in store


def test_bad_arguments(store: Store) -> None:
    with pytest.raises(ValueError):
        store.set("", "x")
    with pytest.raises(TypeError):
        store.set("n", 5)  # type: ignore[arg-type]
