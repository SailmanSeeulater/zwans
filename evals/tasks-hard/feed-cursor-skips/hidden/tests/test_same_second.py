from datetime import UTC, datetime, timedelta

import pytest
from conftest import Clock, walk
from feedsvc.api import Api
from feedsvc.backends import MemoryBackend, SQLiteBackend
from feedsvc.importer import import_export
from feedsvc.service import FeedService

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def make(request):
    """Builds a FeedService on each backend, with a clock that steps by `step` seconds."""
    services = []

    def build(step: int = 60) -> FeedService:
        backend = MemoryBackend() if request.param == "memory" else SQLiteBackend()
        service = FeedService(backend, Clock(T0, timedelta(seconds=step)))
        services.append(service)
        return service

    yield build
    for service in services:
        service.backend.close()


def test_posts_imported_on_one_day_are_all_shown_once(make) -> None:
    service = make()
    export = {
        "author": "ada",
        "posts": [{"date": "2019-05-03", "text": f"old post {n}"} for n in range(25)],
    }
    import_export(service, export)

    pages = walk(service, "ada", limit=10)

    assert [len(page) for page in pages] == [10, 10, 5]
    ids = sum(pages, [])
    assert ids == sorted(ids, reverse=True)
    assert len(set(ids)) == 25


def test_same_timestamp_posts_are_ordered_by_id_highest_first(make) -> None:
    service = make(step=0)
    ids = [service.publish("ada", f"p{n}").id for n in range(6)]

    assert [post.id for post in service.home("ada", limit=3).items] == ids[::-1][:3]
    assert [post.id for post in service.profile("ada").items] == ids[::-1]


def test_ties_on_every_page_boundary(make) -> None:
    service = make()
    service.follow("ada", "grace")
    expected = []
    for minute, count in enumerate([3, 4, 1, 5, 2, 3]):
        at = T0 + timedelta(minutes=minute)
        expected += [
            service.publish("grace" if n % 2 else "ada", f"m{minute} n{n}", at=at)
            for n in range(count)
        ]
    expected.sort(key=lambda post: (post.created_at, post.id), reverse=True)

    for limit in (1, 2, 3, 4, 5, 7):
        assert sum(walk(service, "ada", limit=limit), []) == [post.id for post in expected], limit


def test_posts_published_in_the_same_second_during_a_scroll(make) -> None:
    service = make(step=0)
    service.follow("ada", "grace")
    old = [service.publish("grace", f"old {n}").id for n in range(12)]
    first = service.home("ada", limit=5)
    new = [service.publish("grace", f"new {n}").id for n in range(2)]

    seen = [post.id for post in first.items]
    page = first
    while page.next:
        assert len(seen) < 100, "paging never ends"
        page = service.home("ada", page.next, limit=5)
        seen += [post.id for post in page.items]

    assert seen == old[::-1]
    assert [post.id for post in service.refresh("ada", first.top).items] == new[::-1]


def test_refresh_finds_a_post_from_the_same_second_as_the_top(make) -> None:
    service = make(step=0)
    service.publish("ada", "first")
    top = service.home("ada").top

    second = service.publish("ada", "second, same second")
    fresh = service.refresh("ada", top)

    assert [post.id for post in fresh.items] == [second.id]
    assert service.refresh("ada", fresh.top).items == []


def test_deleting_the_last_post_of_a_page_mid_scroll(make) -> None:
    service = make(step=0)
    ids = [service.publish("ada", f"p{n}").id for n in range(9)]
    first = service.home("ada", limit=4)
    service.delete("ada", first.items[-1].id)

    seen = [post.id for post in first.items]
    page = first
    while page.next:
        assert len(seen) < 100, "paging never ends"
        page = service.home("ada", page.next, limit=4)
        seen += [post.id for post in page.items]

    assert seen == ids[::-1]


def test_scrolling_an_imported_blog_through_the_api() -> None:
    service = FeedService(SQLiteBackend(), Clock(T0))
    service.follow("ada", "grace")
    export = {"author": "grace", "posts": []}
    for day in range(1, 6):
        export["posts"] += [
            {"date": f"2018-11-0{day}", "text": f"day {day} post {n}"} for n in range(7)
        ]
    import_export(service, export)
    service.publish("grace", "back on the new app")
    api = Api(service)

    bodies = []
    status, feed = api.handle("GET", "/feed?user=ada&limit=20")
    bodies += [item["body"] for item in feed["items"]]
    while "next" in feed:
        assert len(bodies) < 500, "paging never ends"
        status, feed = api.handle("GET", f"/feed?user=ada&limit=20&cursor={feed['next']}")
        assert status == 200
        bodies += [item["body"] for item in feed["items"]]

    assert len(bodies) == 36
    assert len(set(bodies)) == 36
    assert bodies[0] == "back on the new app"
    assert bodies[1:8] == [f"day 5 post {n}" for n in range(6, -1, -1)]
    assert bodies[-1] == "day 1 post 0"
