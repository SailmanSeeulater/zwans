import pytest
from markbook.collection import Collection
from markbook.model import DuplicateUrl, MarkbookError, NotFound
from markbook.urls import normalize_url


def test_urls_are_normalised_for_comparison() -> None:
    assert normalize_url("HTTPS://Example.com:443/a/#top") == "https://example.com/a"
    assert normalize_url("http://example.com:8080/") == "http://example.com:8080"
    assert normalize_url("https://example.com/?q=1") == "https://example.com?q=1"


def test_adding_hands_out_ids_that_are_never_reused() -> None:
    collection = Collection()
    first = collection.add("https://a.example/", "A", added="2024-01-01")
    second = collection.add("https://b.example/", added="2024-01-01")
    assert (first.id, second.id) == (1, 2)
    assert second.title == "https://b.example/"
    collection.remove(2)
    assert collection.add("https://c.example/", "C").id == 3


def test_the_same_page_cannot_be_added_twice() -> None:
    collection = Collection()
    collection.add("https://example.com/docs/", "Docs")
    with pytest.raises(DuplicateUrl):
        collection.add("HTTPS://EXAMPLE.com/docs#intro", "Docs again")


def test_only_web_urls() -> None:
    with pytest.raises(MarkbookError):
        Collection().add("javascript:alert(1)", "Nope")


def test_unknown_ids() -> None:
    collection = Collection()
    for action in (collection.get, collection.remove, collection.visit, collection.star):
        with pytest.raises(NotFound):
            action(42)


def test_stars_and_visits() -> None:
    collection = Collection()
    collection.add("https://a.example/", "A")
    collection.add("https://b.example/", "B", starred=True)
    collection.visit(1)
    collection.visit(1)
    collection.star(2, False)
    collection.star(1)
    assert [(b.id, b.visits, b.starred) for b in collection] == [(1, 2, True), (2, 0, False)]
    assert [b.id for b in collection.starred()] == [1]
