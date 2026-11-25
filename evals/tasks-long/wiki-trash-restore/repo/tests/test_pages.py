import pytest
from conftest import kitchen
from leafwiki import InvalidTitle, PageExists, PageNotFound, RevisionNotFound


def test_a_new_page_has_one_revision(wiki) -> None:
    page = wiki.create_page("Kettle", "Boil water.", "ana", tags=["Kitchen"])
    assert page.title == "Kettle"
    assert page.slug == "kettle"
    assert page.id == "p1"
    assert [r.number for r in page.revisions] == [1]
    assert page.current.author == "ana"
    assert page.current.at == page.created_at == "2026-03-01T09:01:00Z"
    assert page.tags == ["kitchen"]


def test_titles_are_matched_by_their_slug(wiki) -> None:
    wiki.create_page("Front Page", "hi")
    assert wiki.page("front   page").title == "Front Page"
    assert wiki.exists("FRONT PAGE")
    with pytest.raises(PageExists):
        wiki.create_page("front page", "again")


def test_bad_titles_are_refused(wiki) -> None:
    for title in ("", "   ", "a/b", "[[x]]", ".hidden", "x" * 121):
        with pytest.raises(InvalidTitle):
            wiki.create_page(title, "body")


def test_editing_adds_a_revision_unless_nothing_changed(wiki) -> None:
    wiki.create_page("Kettle", "one two", "ana")
    wiki.edit_page("Kettle", "one two three", "bo")
    page = wiki.edit_page("Kettle", "one two three", "cy")
    assert [r.number for r in page.revisions] == [1, 2]
    assert page.current.summary == "+1 words"
    assert page.current.author == "bo"


def test_revert_brings_back_old_text_as_a_new_revision(wiki) -> None:
    wiki.create_page("Kettle", "first", "ana")
    wiki.edit_page("Kettle", "second", "bo")
    page = wiki.revert("Kettle", 1, "cy")
    assert page.body == "first"
    assert page.current.number == 3
    assert page.current.summary == "Reverted to revision 1"
    with pytest.raises(RevisionNotFound):
        wiki.revert("Kettle", 9)


def test_diff_between_revisions(wiki) -> None:
    wiki.create_page("Kettle", "line one\nline two\n")
    wiki.edit_page("Kettle", "line one\nline 2\n")
    text = wiki.diff("Kettle", 1, 2)
    assert "-line two" in text and "+line 2" in text


def test_pages_are_listed_by_title(wiki) -> None:
    for title in ("beta", "Alpha", "gamma"):
        wiki.create_page(title, "x")
    assert wiki.titles() == ["Alpha", "beta", "gamma"]


def test_rename_keeps_history_and_frees_the_old_title(wiki) -> None:
    wiki.create_page("Kettle", "first", "ana")
    wiki.edit_page("Kettle", "second", "ana")
    page = wiki.rename_page("Kettle", "Electric Kettle", "bo")
    assert page.id == "p1"
    assert [r.body for r in page.revisions] == ["first", "second"]
    assert not wiki.exists("Kettle")
    wiki.create_page("Kettle", "a new one")
    assert wiki.titles() == ["Electric Kettle", "Kettle"]


def test_rename_to_a_taken_title_is_refused(wiki) -> None:
    wiki.create_page("Kettle", "x")
    wiki.create_page("Teapot", "y")
    with pytest.raises(PageExists):
        wiki.rename_page("Kettle", "teapot")
    assert wiki.rename_page("Kettle", "kettle").title == "kettle"


def test_deleted_pages_are_gone(wiki) -> None:
    kitchen(wiki)
    wiki.delete_page("Kettle", "ana")
    assert wiki.titles() == ["Front Page", "Teapot"]
    for call in (wiki.page, wiki.history, wiki.comments, wiki.watchers):
        with pytest.raises(PageNotFound):
            call("Kettle")
    with pytest.raises(PageNotFound):
        wiki.edit_page("Kettle", "back?")


def test_page_ids_are_never_reused(wiki) -> None:
    wiki.create_page("A", "x")
    wiki.delete_page("A")
    assert wiki.create_page("A", "y").id == "p2"
