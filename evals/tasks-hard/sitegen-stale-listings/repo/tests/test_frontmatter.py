from datetime import date, datetime

import pytest
from sitegen.frontmatter import FrontMatterError, parse


def test_values_are_typed() -> None:
    meta, body = parse(
        "---\ntitle: Hello: world\ndate: 2026-03-14\ntime: 2026-03-14 09:30\n"
        "tags: [a, 'b, c', d]\ndraft: no\ncount: 3\nempty: []\n---\nBody\n"
    )
    assert meta == {
        "title": "Hello: world",
        "date": date(2026, 3, 14),
        "time": datetime(2026, 3, 14, 9, 30),
        "tags": ["a", "b, c", "d"],
        "draft": False,
        "count": 3,
        "empty": [],
    }
    assert body == "Body\n"


def test_no_front_matter() -> None:
    assert parse("Just text\n") == ({}, "Just text\n")


def test_unterminated_front_matter() -> None:
    with pytest.raises(FrontMatterError, match="never ends"):
        parse("---\ntitle: x\n")


def test_duplicate_keys_are_an_error() -> None:
    with pytest.raises(FrontMatterError, match="twice"):
        parse("---\ntitle: a\ntitle: b\n---\n")


def test_bad_dates_are_an_error() -> None:
    with pytest.raises(FrontMatterError, match="not a date"):
        parse("---\ndate: 2026-02-30\n---\n")
