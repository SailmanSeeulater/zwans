import json

import pytest
from conftest import sample
from markbook import store
from markbook.collection import Collection
from markbook.schema import CURRENT_VERSION, SchemaError, validate


def test_a_missing_file_is_an_empty_collection(tmp_path) -> None:
    collection = store.load(tmp_path / "nothing-here.json")
    assert len(collection) == 0
    assert collection.loaded_version is None


def test_save_and_load_round_trip(tmp_path) -> None:
    path = tmp_path / "bookmarks.json"
    collection = Collection()
    collection.add("https://docs.python.org/3/", "Python docs", added="2024-05-01")
    collection.add("https://www.gutenberg.org/", "Project Gutenberg", starred=True, added="")
    collection.visit(1)
    store.save(collection, path)

    again = store.load(path)
    assert [b.to_dict() for b in again] == [b.to_dict() for b in collection]
    assert again.next_id == 3
    assert again.loaded_version == CURRENT_VERSION
    assert json.loads(path.read_text("utf-8"))["version"] == CURRENT_VERSION


@pytest.mark.parametrize("version", range(1, CURRENT_VERSION))
def test_saving_an_old_file_upgrades_it_and_keeps_a_backup(old_file, version) -> None:
    path = old_file(version)
    original = path.read_text("utf-8")
    collection = store.load(path)
    collection.add("https://example.org/new", "New")
    store.save(collection, path)

    assert json.loads(path.read_text("utf-8"))["version"] == CURRENT_VERSION
    backup = path.with_name(f"{path.name}.v{version}.bak")
    assert backup.read_text("utf-8") == original

    collection.add("https://example.org/newer", "Newer")
    store.save(collection, path)
    assert backup.read_text("utf-8") == original
    assert len(store.load(path)) == len(collection)


def test_a_current_file_gets_no_backup(old_file) -> None:
    path = old_file(CURRENT_VERSION)
    store.save(store.load(path), path)
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]


def valid() -> dict:
    return {
        "version": CURRENT_VERSION,
        "next_id": 3,
        "bookmarks": [
            {
                "id": 1,
                "url": "https://a.example/",
                "title": "A",
                "folder": "Dev/Python",
                "added": "2024-01-01",
                "visits": 0,
                "starred": False,
            },
            {
                "id": 2,
                "url": "http://b.example/",
                "title": "B",
                "folder": "",
                "added": "",
                "visits": 3,
                "starred": True,
            },
        ],
    }


def test_the_valid_document_is_valid() -> None:
    validate(valid())


@pytest.mark.parametrize(
    "spoil",
    [
        lambda d: d.update(extra=1),
        lambda d: d.update(version=CURRENT_VERSION - 1),
        lambda d: d.update(next_id=2),
        lambda d: d["bookmarks"][0].update(colour="red"),
        lambda d: d["bookmarks"][0].pop("visits"),
        lambda d: d["bookmarks"][0].update(id=True),
        lambda d: d["bookmarks"][1].update(id=1),
        lambda d: d["bookmarks"][0].update(url="ftp://a.example/"),
        lambda d: d["bookmarks"][0].update(folder="Dev//Python"),
        lambda d: d["bookmarks"][0].update(folder=" Dev"),
        lambda d: d["bookmarks"][0].update(added="01-01-2024"),
        lambda d: d["bookmarks"][0].update(visits=-1),
        lambda d: d["bookmarks"][0].update(starred="yes"),
    ],
)
def test_invalid_documents_are_refused(spoil) -> None:
    doc = valid()
    spoil(doc)
    with pytest.raises(SchemaError):
        validate(doc)


def test_an_invalid_file_is_not_loaded(tmp_path) -> None:
    doc = sample(CURRENT_VERSION)
    doc["bookmarks"][0]["visits"] = "many"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(doc), "utf-8")
    with pytest.raises(SchemaError):
        store.load(path)
