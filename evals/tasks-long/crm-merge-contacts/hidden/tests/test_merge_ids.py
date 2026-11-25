"""B's id keeps working everywhere a contact id is accepted, and is never reused."""

import pytest
from conftest import world
from orbit.errors import NotFound


@pytest.fixture
def ids(crm):
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    return ids


def test_looking_b_up_gives_a(crm, ids) -> None:
    assert crm.contact(ids["b"]).id == ids["a"]
    assert crm.contact(ids["b"]) == crm.contact(ids["a"])


def test_changing_b_changes_a(crm, ids) -> None:
    assert crm.update_contact(ids["b"], title="Countess of Lovelace").id == ids["a"]
    assert crm.contact(ids["a"]).title == "Countess of Lovelace"
    crm.tag(ids["b"], "poet")
    crm.untag(ids["b"], "vip")
    assert crm.contact(ids["a"]).tags == ["looms", "poet"]
    crm.set_field(ids["b"], "seats", 9)
    assert crm.contact(ids["a"]).fields["seats"] == 9
    crm.archive_contact(ids["b"])
    assert crm.contact(ids["a"]).status == "archived"


def test_logging_against_b_logs_against_a(crm, ids) -> None:
    note = crm.add_note(ids["b"], "Logged with the old id")
    task = crm.add_task(ids["b"], "Follow up")
    email = crm.log_email(ids["b"], "Hello again")
    assert (note.contact_id, task.contact_id, email.contact_id) == (ids["a"],) * 3
    assert email.address == "ada@analytical.example"
    assert crm.timeline(ids["a"])[-1].contact_id == ids["a"]


def test_listing_by_b_lists_as(crm, ids) -> None:
    assert crm.notes(ids["b"]) == crm.notes(ids["a"])
    assert crm.tasks(ids["b"]) == crm.tasks(ids["a"])
    assert crm.emails(ids["b"]) == crm.emails(ids["a"])
    assert crm.timeline(ids["b"]) == crm.timeline(ids["a"])
    assert len(crm.timeline(ids["b"])) > 5
    assert crm.duplicates_of(ids["b"]) == crm.duplicates_of(ids["a"])


def test_deals_accept_b(crm, ids) -> None:
    deal = crm.add_deal("New engine", 1000, [ids["b"], ids["charles"]])
    assert deal.contact_ids == [ids["a"], ids["charles"]]
    assert ids["a"] in crm.add_deal_contact(ids["d3"], ids["b"]).contact_ids
    assert crm.remove_deal_contact(ids["d1"], ids["b"]).contact_ids == [ids["charles"]]
    moved = crm.move_deal(ids["d3"], "qualified", contact_id=ids["b"])
    assert moved.history()[-1].contact_id == ids["a"]


def test_companies_and_webhooks_accept_b(crm, ids) -> None:
    assert crm.set_primary_contact(ids["engines"], ids["b"]).primary_contact_id == ids["a"]
    assert crm.subscribe("https://hooks.example/x", contact_id=ids["b"]).contact_id == ids["a"]


def test_merging_with_b_merges_with_a(crm, ids) -> None:
    crm.merge_contacts(ids["b"], ids["charles"])
    assert crm.contact(ids["charles"]).id == ids["a"]
    assert crm.deal(ids["d1"]).contact_ids == [ids["a"]]


def test_merges_in_a_row_are_followed(crm, ids) -> None:
    crm.merge_contacts(ids["grace"], ids["a"])
    assert crm.contact(ids["b"]).id == ids["grace"]
    assert crm.contact(ids["a"]).id == ids["grace"]
    assert "Collects punched cards" in [n.body for n in crm.notes(ids["b"])]
    assert crm.add_note(ids["b"], "Twice merged").contact_id == ids["grace"]


def test_unknown_ids_are_still_unknown(crm, ids) -> None:
    with pytest.raises(NotFound):
        crm.contact("c99")
    with pytest.raises(NotFound):
        crm.add_note("c99", "nobody")


def test_a_merged_id_is_never_given_to_a_new_contact(crm) -> None:
    keep = crm.add_contact("Ada", "Lovelace")
    newest = crm.add_contact("Ada", "Lovelace")
    crm.merge_contacts(keep.id, newest.id)
    fresh = crm.add_contact("Grace", "Hopper")
    assert fresh.id != newest.id
    assert crm.contact(newest.id).id == keep.id
    assert crm.contact(fresh.id).first_name == "Grace"
