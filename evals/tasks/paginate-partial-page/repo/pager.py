"""Split a list of results into numbered pages for the listing views."""

from dataclasses import dataclass


class PageNotFound(Exception):
    pass


@dataclass
class Page[T]:
    items: list[T]
    number: int  # 1-based
    total_pages: int

    @property
    def has_next(self) -> bool:
        return self.number < self.total_pages

    @property
    def has_previous(self) -> bool:
        return self.number > 1


def count_pages(total: int, per_page: int) -> int:
    """How many pages `total` items fill. An empty listing still has one (empty) page."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    return max(1, total // per_page)


def paginate[T](items: list[T], number: int, per_page: int = 20) -> Page[T]:
    total_pages = count_pages(len(items), per_page)
    if not 1 <= number <= total_pages:
        raise PageNotFound(f"page {number} of {total_pages}")
    start = (number - 1) * per_page
    return Page(items[start : start + per_page], number, total_pages)
