import pytest

from pager import PageNotFound, count_pages, paginate
from views import render_results


@pytest.mark.parametrize(
    ("total", "per_page", "expected"),
    [
        (0, 20, 1),
        (1, 20, 1),
        (19, 20, 1),
        (20, 20, 1),
        (21, 20, 2),
        (40, 20, 2),
        (41, 20, 3),
        (45, 20, 3),
        (7, 1, 7),
        (10, 3, 4),
    ],
)
def test_count_pages(total: int, per_page: int, expected: int) -> None:
    assert count_pages(total, per_page) == expected


def test_no_phantom_page_on_exact_multiple() -> None:
    page = paginate(list(range(40)), 2, per_page=20)

    assert page.items == list(range(20, 40))
    assert not page.has_next
    with pytest.raises(PageNotFound):
        paginate(list(range(40)), 3, per_page=20)


def test_page_past_the_end_does_not_exist() -> None:
    with pytest.raises(PageNotFound):
        paginate(list(range(45)), 4, per_page=20)


def test_render_last_partial_page() -> None:
    results = [f"r{n}" for n in range(7)]

    text = render_results(results, 3, per_page=3)

    assert text.splitlines() == ["- r6", "", "< page 2 | Page 3 of 3"]


def test_per_page_must_be_positive() -> None:
    with pytest.raises(ValueError):
        count_pages(10, 0)
