from datetime import UTC, datetime

import pytest
from conftest import walk
from feedsvc.cursor import CursorError
from feedsvc.models import ValidationError


def test_home_feed_has_followed_authors_and_your_own_posts(service) -> None:
    service.follow("ada", "grace")
    service.publish("grace", "hello from grace")
    service.publish("linus", "not followed")
    service.publish("ada", "my own post")

    page = service.home("ada")

    assert [(p.author, p.body) for p in page.items] == [
        ("ada", "my own post"),
        ("grace", "hello from grace"),
    ]
    assert page.next is None
    assert page.top is not None


def test_timestamps_are_kept_to_the_second(service) -> None:
    post = service.publish("ada", "x", at=datetime(2026, 3, 1, 9, 30, 15, 999999, tzinfo=UTC))
    assert post.created_at == datetime(2026, 3, 1, 9, 30, 15, tzinfo=UTC)
    assert post.to_dict()["created_at"] == "2026-03-01T09:30:15Z"


def test_paging_through_a_feed(service) -> None:
    service.follow("ada", "grace")
    ids = [service.publish("grace" if n % 2 else "ada", f"post {n}").id for n in range(1, 24)]

    pages = walk(service, "ada", limit=10)

    assert [len(page) for page in pages] == [10, 10, 3]
    assert sum(pages, []) == list(reversed(ids))


def test_an_exact_multiple_of_the_limit_has_no_empty_last_page(service) -> None:
    for n in range(20):
        service.publish("ada", f"post {n}")
    assert [len(page) for page in walk(service, "ada", limit=10)] == [10, 10]


def test_new_posts_dont_shift_later_pages(service) -> None:
    for n in range(15):
        service.publish("ada", f"old {n}")
    first = service.home("ada", limit=10)
    service.publish("ada", "brand new")

    second = service.home("ada", first.next, limit=10)

    assert [p.body for p in second.items] == [f"old {n}" for n in range(4, -1, -1)]


def test_refresh_returns_whats_new_at_the_top(service) -> None:
    service.follow("ada", "grace")
    service.publish("grace", "before")
    first = service.home("ada")

    service.publish("grace", "after 1")
    service.publish("ada", "after 2")
    fresh = service.refresh("ada", first.top)

    assert [p.body for p in fresh.items] == ["after 2", "after 1"]
    assert service.refresh("ada", fresh.top).items == []
    assert service.refresh("ada", fresh.top).top == fresh.top


def test_refresh_from_an_empty_feed(service) -> None:
    first = service.home("ada")
    assert first.items == []
    service.publish("ada", "first ever")
    assert [p.body for p in service.refresh("ada", first.top).items] == ["first ever"]


def test_muted_authors_are_left_out(service) -> None:
    service.follow("ada", "grace")
    service.follow("ada", "linus")
    service.publish("grace", "g")
    service.publish("linus", "l")
    service.mute("ada", "linus")

    assert [p.body for p in service.home("ada").items] == ["g"]
    service.unmute("ada", "linus")
    assert [p.body for p in service.home("ada").items] == ["l", "g"]


def test_profile(service) -> None:
    service.publish("ada", "one")
    service.publish("grace", "other")
    service.publish("ada", "two")
    assert [p.body for p in service.profile("ada").items] == ["two", "one"]


def test_limits(service) -> None:
    for n in range(120):
        service.publish("ada", f"p{n}")
    assert len(service.home("ada", limit=500).items) == 100
    assert len(service.home("ada").items) == 20
    with pytest.raises(ValidationError):
        service.home("ada", limit=0)


def test_bad_cursors(service) -> None:
    for token in ("nonsense", "eyJ2Ijo5OX0", ""):
        if token:
            with pytest.raises(CursorError):
                service.home("ada", token)


def test_deprecated_offset_paging(service) -> None:
    for n in range(5):
        service.publish("ada", f"p{n}")
    first = service.home_by_page("ada", 1, limit=2)
    assert [p.body for p in first.items] == ["p4", "p3"]
    assert first.next == "2"
    assert service.home_by_page("ada", 3, limit=2).next is None


def test_validation(service) -> None:
    with pytest.raises(ValidationError):
        service.publish("ada", "   ")
    with pytest.raises(ValidationError):
        service.publish("not a name!", "x")
    with pytest.raises(ValidationError):
        service.follow("ada", "ada")
