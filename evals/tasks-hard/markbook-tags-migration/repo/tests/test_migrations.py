import copy

import pytest
from conftest import sample
from markbook import store
from markbook.migrations import MIGRATIONS, MigrationError, migrate
from markbook.schema import CURRENT_VERSION, validate


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


def test_format_1_categories_become_folders(old_file) -> None:
    collection = store.load(old_file(1))
    assert [(b.id, b.title, b.folder, b.added) for b in collection] == [
        (1, "Python docs", "Dev/Python", "2021-03-04"),
        (2, "Project Gutenberg", "Reading/Long Reads", "2021-05-17"),
        (3, "Hacker News", "", ""),
        (4, "pytest", "Dev/Python/Testing", "2021-06-01"),
    ]
    assert {(b.visits, b.starred) for b in collection} == {(0, False)}
    assert collection.next_id == 5


def test_format_2_keeps_ids_and_visits(old_file) -> None:
    collection = store.load(old_file(2))
    assert [(b.id, b.folder, b.visits, b.starred) for b in collection] == [
        (1, "Dev/Web", 31, False),
        (2, "Home/Cooking", 4, False),
        (4, "Dev/Python/python", 0, False),
    ]
    assert collection.next_id == 5


def test_format_3_loads_as_it_is(old_file) -> None:
    collection = store.load(old_file(3))
    assert [(b.id, b.folder, b.visits, b.starred) for b in collection] == [
        (2, "Dev/Python/Web Frameworks", 9, True),
        (5, "Home/Cooking", 2, False),
        (6, "", 0, False),
    ]
    assert collection.next_id == 7
