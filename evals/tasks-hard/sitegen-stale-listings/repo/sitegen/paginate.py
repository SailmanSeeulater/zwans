from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class Pager(Generic[T]):
    number: int  # 1-based
    count: int  # how many pages there are
    items: list[T]
    base: str  # the URL of page 1, "" for the home page

    @property
    def url(self) -> str:
        return page_url(self.base, self.number)

    @property
    def output(self) -> str:
        return self.url + "index.html"

    @property
    def prev_url(self) -> str | None:
        return page_url(self.base, self.number - 1) if self.number > 1 else None

    @property
    def next_url(self) -> str | None:
        return page_url(self.base, self.number + 1) if self.number < self.count else None


def page_url(base: str, number: int) -> str:
    return base if number == 1 else f"{base}page/{number}/"


def paginate(items: list[T], per_page: int, base: str = "") -> list[Pager[T]]:
    """Split items into pages. There is always at least one page, even if it is empty."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    chunks = [items[start : start + per_page] for start in range(0, len(items), per_page)]
    chunks = chunks or [[]]
    return [Pager(n, len(chunks), chunk, base) for n, chunk in enumerate(chunks, start=1)]
