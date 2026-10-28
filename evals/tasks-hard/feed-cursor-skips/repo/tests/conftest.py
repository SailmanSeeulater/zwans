from datetime import UTC, datetime, timedelta

import pytest
from feedsvc.backends import MemoryBackend
from feedsvc.service import FeedService


class Clock:
    """A clock that moves forward by `step` every time it is read."""

    def __init__(
        self,
        start: datetime = datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        step: timedelta = timedelta(minutes=1),
    ) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(clock: Clock) -> FeedService:
    return FeedService(MemoryBackend(), clock)


def walk(service: FeedService, user: str, limit: int) -> list[list[int]]:
    """Every page of a user's home feed, as lists of post ids."""
    pages = []
    page = service.home(user, limit=limit)
    pages.append([post.id for post in page.items])
    while page.next:
        assert len(pages) < 200, "paging never ends"
        page = service.home(user, page.next, limit=limit)
        pages.append([post.id for post in page.items])
    return pages
