import pytest

from pager import PageNotFound, paginate


def test_first_page() -> None:
    page = paginate(list(range(45)), 1, per_page=20)

    assert page.items == list(range(20))
    assert page.has_next
    assert not page.has_previous


def test_last_partial_page() -> None:
    page = paginate(list(range(45)), 3, per_page=20)

    assert page.items == [40, 41, 42, 43, 44]
    assert page.total_pages == 3
    assert not page.has_next


def test_page_zero_does_not_exist() -> None:
    with pytest.raises(PageNotFound):
        paginate(list(range(10)), 0, per_page=5)
