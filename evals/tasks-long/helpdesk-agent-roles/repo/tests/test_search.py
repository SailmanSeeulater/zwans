import pytest
from deskline import search
from deskline.errors import QueryError
from deskline.services import tickets


@pytest.fixture
def three(desk, ctx, seeded):
    a = tickets.create(ctx, seeded["jane"].id, "Printer jams", "Paper everywhere", priority="high", tags=["hardware"])
    b = tickets.create(ctx, seeded["bob"].id, "Refund", "Double charge on my invoice")
    c = tickets.create(ctx, seeded["jane"].id, "Login", "Cannot log in", tags=["web", "spam"])
    tickets.assign(ctx, a.id, "maria")
    return a, b, c


def ids(rows):
    return sorted(r["id"] for r in rows)


def test_field_terms(ctx, three) -> None:
    a, b, c = three
    assert ids(search.run(ctx, "priority:high")) == [a.id]
    assert ids(search.run(ctx, "queue:billing")) == [b.id]
    assert ids(search.run(ctx, "tag:web,hardware")) == [a.id, c.id]
    assert ids(search.run(ctx, "-tag:spam")) == [a.id, b.id]
    assert ids(search.run(ctx, "assignee:none")) == [b.id, c.id]
    assert ids(search.run(ctx, "is:unassigned status:new")) == [b.id, c.id]


def test_requester_terms(ctx, three) -> None:
    a, b, c = three
    assert ids(search.run(ctx, "requester:jane")) == [a.id, c.id]
    assert ids(search.run(ctx, "email:stone.example")) == [b.id]
    assert ids(search.run(ctx, "phone:5550101")) == [a.id, c.id]


def test_free_text_and_phrases(ctx, three) -> None:
    a, b, c = three
    assert ids(search.run(ctx, "invoice")) == [b.id]
    assert ids(search.run(ctx, '"paper everywhere"')) == [a.id]


def test_rows_carry_the_requester(ctx, three) -> None:
    rows = search.run(ctx, "refund")
    assert rows[0]["requester"] == "Bob Stone"
    assert rows[0]["requester_email"] == "bob@stone.example"


def test_sorting_and_limits(ctx, three) -> None:
    a, b, c = three
    assert [r["id"] for r in search.run(ctx, "", sort="id")] == [a.id, b.id, c.id]
    assert len(search.run(ctx, "", limit=2)) == 2


def test_bad_queries(ctx, three) -> None:
    with pytest.raises(QueryError):
        search.run(ctx, "status:sleeping")
    with pytest.raises(QueryError):
        search.run(ctx, "assignee:me")
    with pytest.raises(QueryError):
        search.run(ctx, "created:2026-01-01")
