import pytest

from stockflow import ConcurrencyError, FileEventStore, InMemoryEventStore
from stockflow.errors import StoreError
from stockflow.events import NewEvent


def event(n: int) -> NewEvent:
    return NewEvent("StockReceived", 2, {"quantity": n, "lot": "L"})


@pytest.fixture(params=["memory", "file"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryEventStore()
    return FileEventStore(tmp_path / "data", fsync=False)


def test_append_and_read(store) -> None:
    assert store.append("item-a", [event(1), event(2)], expected_version=0) == 2
    assert store.append("item-b", [event(3)], expected_version=0) == 1
    assert store.append("item-a", [event(4)], expected_version=2) == 3

    assert [e.data["quantity"] for e in store.read("item-a")] == [1, 2, 4]
    assert [e.position for e in store.read("item-a", after=1)] == [2, 3]
    assert [(e.stream, e.global_position) for e in store.read_all(after=2)] == [
        ("item-b", 3),
        ("item-a", 4),
    ]
    assert store.version("item-a") == 3 and store.version("item-zzz") == 0
    assert sorted(store.streams()) == ["item-a", "item-b"]


def test_a_stale_expected_version_is_refused(store) -> None:
    store.append("item-a", [event(1)], expected_version=0)

    with pytest.raises(ConcurrencyError) as caught:
        store.append("item-a", [event(2)], expected_version=0)

    assert (caught.value.expected, caught.value.actual) == (0, 1)
    assert store.version("item-a") == 1


def test_readers_cant_change_what_is_stored(store) -> None:
    store.append("item-a", [event(1)], expected_version=0)

    store.read("item-a")[0].data["quantity"] = 99

    assert store.read("item-a")[0].data["quantity"] == 1


def test_bad_stream_names(store) -> None:
    with pytest.raises(StoreError):
        store.append("no dashes here", [event(1)], expected_version=0)


def test_a_file_store_reopens_where_it_left_off(tmp_path) -> None:
    FileEventStore(tmp_path, fsync=False).append("item-a", [event(1), event(2)], 0)

    again = FileEventStore(tmp_path, fsync=False)

    assert again.version("item-a") == 2
    assert again.append("item-a", [event(3)], expected_version=2) == 3


def test_two_file_stores_on_one_directory_see_each_other(tmp_path) -> None:
    first = FileEventStore(tmp_path, fsync=False)
    second = FileEventStore(tmp_path, fsync=False)
    first.append("item-a", [event(1)], expected_version=0)

    with pytest.raises(ConcurrencyError):
        second.append("item-a", [event(2)], expected_version=0)
    assert second.append("item-a", [event(2)], expected_version=1) == 2
    assert [e.data["quantity"] for e in first.read("item-a")] == [1, 2]


def test_a_half_written_line_is_left_for_later(tmp_path) -> None:
    store = FileEventStore(tmp_path, fsync=False)
    store.append("item-a", [event(1)], expected_version=0)
    with (tmp_path / "events.jsonl").open("ab") as handle:
        handle.write(b'{"stream": "item-a", "posi')

    assert FileEventStore(tmp_path, fsync=False).version("item-a") == 1
