import copy
import json

import pytest
from conftest import sample
from markbook import store
from markbook.migrations import MIGRATIONS, MigrationError, migrate
from markbook.schema import CURRENT_VERSION, validate


def test_the_current_format_is_4() -> None:
    assert CURRENT_VERSION == 4


def test_there_is_a_migration_from_every_old_format() -> None:
    assert sorted(MIGRATIONS) == list(range(1, CURRENT_VERSION))


@pytest.mark.parametrize("version", sorted(MIGRATIONS))
def test_a_migration_moves_one_format_up_and_leaves_its_input_alone(version: int) -> None:
    doc = sample(version)
    before = copy.deepcopy(doc)
    result = MIGRATIONS[version](doc)
    assert doc == before
    assert result["version"] == version + 1


@pytest.mark.parametrize("version", range(1, CURRENT_VERSION + 1))
def test_every_sample_migrates_to_a_valid_current_document(version: int) -> None:
    doc = migrate(sample(version))
    assert doc["version"] == CURRENT_VERSION
    validate(doc)
    for bookmark in doc["bookmarks"]:
        assert "folder" not in bookmark
        assert isinstance(bookmark["tags"], list)


def test_a_current_document_is_left_as_it_is() -> None:
    doc = sample(CURRENT_VERSION)
    assert migrate(doc) is doc


def test_newer_or_unversioned_files_are_refused() -> None:
    with pytest.raises(MigrationError, match="newer"):
        migrate({"version": CURRENT_VERSION + 1, "bookmarks": []})
    with pytest.raises(MigrationError):
        migrate({"bookmarks": []})
    with pytest.raises(MigrationError):
        migrate({"version": "1", "bookmarks": []})


def saved(collection, tmp_path) -> list[dict]:
    """The bookmarks as they are written to a file."""
    path = tmp_path / "saved.json"
    store.save(collection, path)
    return json.loads(path.read_text("utf-8"))["bookmarks"]


def summary(bookmarks: list[dict]) -> list[tuple]:
    for b in bookmarks:
        assert len(set(b["tags"])) == len(b["tags"]), b
    return [
        (b["id"], b["title"], sorted(b["tags"]), b["added"], b["visits"], b["starred"])
        for b in bookmarks
    ]


def test_format_1_categories_become_tags(old_file, tmp_path) -> None:
    collection = store.load(old_file(1))
    assert summary(saved(collection, tmp_path)) == [
        (1, "Python docs", ["dev", "python"], "2021-03-04", 0, False),
        (2, "Project Gutenberg", ["long-reads", "reading"], "2021-05-17", 0, False),
        (3, "Hacker News", [], "", 0, False),
        (4, "pytest", ["dev", "python", "testing"], "2021-06-01", 0, False),
    ]
    assert collection.next_id == 5


def test_format_2_keeps_ids_and_visits(old_file, tmp_path) -> None:
    collection = store.load(old_file(2))
    assert summary(saved(collection, tmp_path)) == [
        (1, "MDN", ["dev", "web"], "2022-01-10", 31, False),
        (2, "BBC Food", ["cooking", "home"], "2022-02-11", 4, False),
        (4, "Real Python", ["dev", "python"], "2022-03-12", 0, False),
    ]
    assert collection.next_id == 5


def test_format_3_folders_become_tags(old_file, tmp_path) -> None:
    collection = store.load(old_file(3))
    assert summary(saved(collection, tmp_path)) == [
        (2, "Django docs", ["dev", "python", "web-frameworks"], "2023-07-01", 9, True),
        (5, "Serious Eats", ["cooking", "home"], "2023-08-02", 2, False),
        (6, "Inbox", [], "", 0, False),
    ]
    assert collection.next_id == 7


def test_the_format_3_migration_on_its_own() -> None:
    doc = MIGRATIONS[3](sample(3))
    assert doc["next_id"] == 7
    assert [(b["id"], sorted(b["tags"])) for b in doc["bookmarks"]] == [
        (2, ["dev", "python", "web-frameworks"]),
        (5, ["cooking", "home"]),
        (6, []),
    ]
    assert all(set(b) == set(sample(4)["bookmarks"][0]) for b in doc["bookmarks"])


def test_format_4_loads_as_it_is(old_file, tmp_path) -> None:
    collection = store.load(old_file(4))
    assert summary(saved(collection, tmp_path)) == [
        (1, "Python docs", ["dev", "python"], "2026-01-02", 5, True),
        (3, "Project Gutenberg", [], "", 0, False),
    ]
