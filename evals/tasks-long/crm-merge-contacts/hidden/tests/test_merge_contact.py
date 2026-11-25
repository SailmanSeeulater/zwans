"""What the kept contact (A) looks like after a merge."""

import pytest
from conftest import world
from orbit.errors import CrmError, NotFound


def merged(crm):
    ids = world(crm)
    before_a = crm.contact(ids["a"])
    before_b = crm.contact(ids["b"])
    result = crm.merge_contacts(ids["a"], ids["b"])
    return ids, before_a, before_b, result


def test_merge_returns_the_kept_contact(crm) -> None:
    ids, _, _, result = merged(crm)
    assert result.id == ids["a"]
    assert crm.contact(ids["a"]) == result


def test_a_keeps_its_own_identity(crm) -> None:
    ids, before_a, _, _ = merged(crm)
    after = crm.contact(ids["a"])
    assert (after.first_name, after.last_name) == ("Ada", "Lovelace")
    assert after.title == before_a.title == ""
    assert after.owner == "sam"
    assert after.source == "conference"
    assert after.status == "active"
    assert after.created_at == before_a.created_at


def test_addresses_and_numbers_are_combined_without_repeats(crm) -> None:
    ids, _, _, _ = merged(crm)
    after = crm.contact(ids["a"])
    assert after.emails == ["ada@analytical.example", "countess@home.example"]
    assert after.phones == ["+44 20 7946 0000", "+44 1632 960111"]


def test_tags_are_combined(crm) -> None:
    ids, _, _, _ = merged(crm)
    assert crm.contact(ids["a"]).tags == ["looms", "vip"]


def test_custom_fields_follow_the_precedence_rule(crm) -> None:
    ids, _, _, _ = merged(crm)
    fields = crm.contact(ids["a"]).fields
    assert fields["size"] == "m"  # A had one
    assert fields["seats"] == 3  # A had one
    assert fields["renewal"] == "2026-09-01"  # only B had one
    assert fields["nickname"] == "Enchantress"  # only B had one
    assert fields["interests"] == ["engines", "poetry", "looms", "cards"]  # multi: union, A first


def test_a_multi_field_only_b_has_is_taken_whole(crm) -> None:
    ids = world(crm)
    crm.set_field(ids["a"], "interests", [])
    crm.merge_contacts(ids["a"], ids["b"])
    assert crm.contact(ids["a"]).fields["interests"] == ["looms", "engines", "cards"]


def test_company_is_kept_or_taken(crm) -> None:
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    assert crm.contact(ids["a"]).company_id == ids["engines"]
    crm.merge_contacts(ids["charles"], ids["a"])
    assert crm.contact(ids["charles"]).company_id == ids["engines"]


def test_last_contacted_is_the_later_of_the_two(crm) -> None:
    ids, before_a, before_b, _ = merged(crm)
    assert before_b.last_contacted_at > before_a.last_contacted_at
    assert crm.contact(ids["a"]).last_contacted_at == before_b.last_contacted_at


def test_last_contacted_stays_when_a_is_later(crm) -> None:
    ids = world(crm)
    email = crm.log_email(ids["a"], "Latest")
    crm.merge_contacts(ids["a"], ids["b"])
    assert crm.contact(ids["a"]).last_contacted_at == email.at
    crm.merge_contacts(ids["grace"], ids["a"])
    assert crm.contact(ids["grace"]).last_contacted_at == email.at


def test_merging_a_contact_into_itself_is_an_error(crm) -> None:
    ids = world(crm)
    with pytest.raises(CrmError):
        crm.merge_contacts(ids["a"], ids["a"])
    crm.merge_contacts(ids["a"], ids["b"])
    with pytest.raises(CrmError):
        crm.merge_contacts(ids["a"], ids["b"])
    with pytest.raises(CrmError):
        crm.merge_contacts(ids["b"], ids["a"])
    assert crm.contact(ids["a"]).emails == ["ada@analytical.example", "countess@home.example"]


def test_unknown_ids_are_not_found(crm) -> None:
    ids = world(crm)
    with pytest.raises(NotFound):
        crm.merge_contacts(ids["a"], "c99")
    with pytest.raises(NotFound):
        crm.merge_contacts("c99", ids["a"])
    assert len(crm.list_contacts()) == 5


def test_b_is_gone_from_the_contact_list(crm) -> None:
    ids, _, _, _ = merged(crm)
    listed = [c.id for c in crm.list_contacts(include_archived=True)]
    assert listed == [ids["a"], ids["charles"], ids["grace"], ids["twin"]]
