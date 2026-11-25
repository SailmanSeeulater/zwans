import pytest
from conftest import kitchen
from leafwiki import Wiki
from leafwiki.errors import QueryError


def titles(hits) -> list[str]:
    return [hit.title for hit in hits]


def test_words_must_all_match(wiki) -> None:
    kitchen(wiki)
    assert titles(wiki.search("kettle")) == ["Kettle", "Teapot", "Front Page"]
    assert titles(wiki.search("kettle vinegar")) == ["Kettle"]
    assert wiki.search("kettle giraffe") == []


def test_stemming_and_case(wiki) -> None:
    kitchen(wiki)
    assert titles(wiki.search("DESCALES")) == ["Kettle"]
    assert titles(wiki.search("strainers")) == ["Teapot"]


def test_phrases_exclusions_tags_and_titles(wiki) -> None:
    kitchen(wiki)
    assert titles(wiki.search('"warm the teapot"')) == ["Teapot"]
    assert titles(wiki.search('"teapot warm"')) == []
    assert titles(wiki.search("kettle -vinegar")) == ["Teapot", "Front Page"]
    assert titles(wiki.search("tag:kitchen")) == ["Kettle", "Teapot"]
    assert titles(wiki.search("kettle -tag:kitchen")) == ["Front Page"]
    assert titles(wiki.search("title:kettle")) == ["Kettle"]


def test_hits_carry_a_snippet(wiki) -> None:
    kitchen(wiki)
    (hit,) = wiki.search("vinegar")
    assert "vinegar" in hit.snippet


def test_bad_queries(wiki) -> None:
    with pytest.raises(QueryError):
        wiki.search('"unclosed')
    assert wiki.search("   ") == []


def test_the_index_follows_edits_renames_and_deletes(wiki) -> None:
    kitchen(wiki)
    wiki.edit_page("Kettle", "Now about limescale only.")
    assert wiki.search("vinegar") == []
    assert titles(wiki.search("limescale")) == ["Kettle"]
    wiki.rename_page("Kettle", "Jug")
    assert titles(wiki.search("limescale")) == ["Jug"]
    wiki.delete_page("Jug")
    assert wiki.search("limescale") == []


def test_the_index_is_saved_and_reused(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    reopened = Wiki.open(folder, clock=clock)
    assert titles(reopened.search("vinegar")) == ["Kettle"]
    assert reopened.index.to_dict() == disk_wiki.index.to_dict()


def test_a_stale_or_missing_index_is_rebuilt_on_open(disk_wiki, folder, clock) -> None:
    kitchen(disk_wiki)
    (folder / "index.json").unlink()
    assert titles(Wiki.open(folder, clock=clock).search("vinegar")) == ["Kettle"]
    (folder / "index.json").write_text('{"version": 1, "generation": 0, "docs": {}, "postings": {}}')
    assert titles(Wiki.open(folder, clock=clock).search("vinegar")) == ["Kettle"]


def test_rebuilding_gives_the_same_index(wiki) -> None:
    kitchen(wiki)
    wiki.edit_page("Teapot", "Rinse with hot water.")
    before = wiki.index.to_dict()
    assert wiki.rebuild_index() == 3
    assert wiki.index.to_dict() == before
