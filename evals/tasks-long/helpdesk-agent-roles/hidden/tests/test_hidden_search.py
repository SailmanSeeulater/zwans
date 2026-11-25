"""Search and saved searches: redacted rows, contact terms, and whose permissions apply."""

import pytest
from conftest import BOB_EMAIL, JANE_EMAIL, REDACTED, leaks
from deskline import search
from deskline.errors import PermissionDenied
from deskline.services import searches, tickets


@pytest.fixture
def two(desk, ctx, people):
    a = tickets.create(ctx, people["jane"].id, "Printer", "It jams", priority="high")
    b = tickets.create(ctx, people["bob"].id, "Refund", "Double charge")
    c = tickets.create(ctx, people["kim"].id, "Quiet one", "Shh")
    return a.id, b.id, c.id


@pytest.mark.parametrize("who", ["vic", "ana"])
def test_search_rows_hide_contacts(as_, two, who) -> None:
    rows = search.run(as_(who), "", sort="id")
    assert [r["requester"] for r in rows] == ["Jane Doe", "Bob Stone", "Kim Quiet"]
    assert [r["requester_email"] for r in rows] == [REDACTED, REDACTED, ""]
    assert leaks(rows) == []


@pytest.mark.parametrize("who", ["lou", "ada"])
def test_leads_see_contacts_in_search(as_, two, who) -> None:
    rows = search.run(as_(who), "", sort="id")
    assert [r["requester_email"] for r in rows] == [JANE_EMAIL, BOB_EMAIL, ""]


@pytest.mark.parametrize("query", ["email:example.org", "phone:5550101", "-email:stone", "printer email:jane"])
def test_contact_terms_need_contact_view(desk, as_, two, query) -> None:
    with pytest.raises(PermissionDenied) as caught:
        search.run(as_("ana"), query)
    assert caught.value.permission == "contact.view"
    assert desk.store.audit[-1].action == "permission.denied"
    assert search.run(as_("lou"), query) is not None


def test_other_terms_are_fine_for_everyone(as_, two) -> None:
    a, b, _ = two
    assert [r["id"] for r in search.run(as_("vic"), "requester:jane priority:high")] == [a]


def test_saving_searches(desk, as_, two) -> None:
    with pytest.raises(PermissionDenied) as caught:
        searches.save_search(as_("vic"), "Mine", "status:new")
    assert caught.value.permission == "search.save"
    with pytest.raises(PermissionDenied) as caught:
        searches.save_search(as_("ana"), "Everyone's", "status:new", shared=True)
    assert caught.value.permission == "search.share"
    assert desk.store.searches == {}
    mine = searches.save_search(as_("ana"), "Mine", "status:new")
    searches.save_search(as_("lou"), "Team", "status:new", shared=True)
    assert [s.name for s in searches.list_searches(as_("vic"))] == ["Team"]
    searches.delete_search(as_("ana"), mine.id)


def test_a_shared_search_run_by_a_viewer_is_redacted(desk, as_, two) -> None:
    team = searches.save_search(as_("lou"), "Everything", "", shared=True, sort="id")
    lead_view = searches.run_saved(as_("lou"), team.id)
    assert lead_view["results"][0]["requester_email"] == JANE_EMAIL
    viewer_view = searches.run_saved(as_("vic"), team.id)
    assert viewer_view["count"] == 3
    assert [r["requester_email"] for r in viewer_view["results"]] == [REDACTED, REDACTED, ""]
    assert leaks(viewer_view) == []


def test_a_saved_contact_search_runs_with_the_runners_permissions(desk, as_, two) -> None:
    a, _, _ = two
    team = searches.save_search(as_("lou"), "Example people", "email:example.org", shared=True)
    assert [r["id"] for r in searches.run_saved(as_("lou"), team.id)["results"]] == [a]
    with pytest.raises(PermissionDenied) as caught:
        searches.run_saved(as_("ana"), team.id)
    assert caught.value.permission == "contact.view"
    with pytest.raises(PermissionDenied):
        searches.run_saved(as_("vic"), team.id)
