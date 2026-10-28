from pathlib import Path

from conftest import Clock, walk
from feedsvc.backends import SQLiteBackend, make_backend
from feedsvc.service import FeedService


def test_posts_and_follows_survive_a_restart(tmp_path: Path) -> None:
    path = str(tmp_path / "feed.db")
    service = FeedService(make_backend("sqlite", path), Clock())
    service.follow("ada", "grace")
    service.publish("grace", "persisted")
    service.backend.close()

    reopened = FeedService(make_backend("sqlite", path), Clock())
    assert [p.body for p in reopened.home("ada").items] == ["persisted"]
    reopened.backend.close()


def test_paging_on_sqlite() -> None:
    service = FeedService(SQLiteBackend(), Clock())
    service.follow("ada", "grace")
    ids = [service.publish("grace" if n % 3 else "ada", f"post {n}").id for n in range(1, 31)]

    pages = walk(service, "ada", limit=7)

    assert [len(page) for page in pages] == [7, 7, 7, 7, 2]
    assert sum(pages, []) == list(reversed(ids))


def test_refresh_on_sqlite() -> None:
    service = FeedService(SQLiteBackend(), Clock())
    service.publish("ada", "one")
    first = service.home("ada")
    service.publish("ada", "two")

    assert [p.body for p in service.refresh("ada", first.top).items] == ["two"]


def test_delete_on_sqlite() -> None:
    service = FeedService(SQLiteBackend(), Clock())
    post = service.publish("ada", "oops")
    service.delete("ada", post.id)
    assert service.home("ada").items == []
