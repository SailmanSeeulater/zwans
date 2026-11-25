import pytest
from conftest import seed
from orbit.errors import InvalidValue, NotFound


def test_a_new_contact_gets_the_next_id(crm) -> None:
    first = crm.add_contact("Ada", "Lovelace")
    second = crm.add_contact("Grace", "Hopper")
    assert (first.id, second.id) == ("c1", "c2")
    assert crm.contact("c2").name == "Grace Hopper"


def test_emails_and_phones_are_cleaned_and_kept_in_order(crm) -> None:
    contact = crm.add_contact(
        "Ada",
        emails=[" ada@analytical.example", "ADA@analytical.example", "ada@home.example"],
        phones=["+44 20  7946 0000", "+44 (20) 7946-0000"],
    )
    assert contact.emails == ["ada@analytical.example", "ada@home.example"]
    assert contact.primary_email == "ada@analytical.example"
    assert contact.phones == ["+44 20 7946 0000"]


def test_a_contact_needs_a_name_or_an_address(crm) -> None:
    with pytest.raises(InvalidValue):
        crm.add_contact("  ")
    assert crm.add_contact("", emails=["x@y.example"]).name == "x@y.example"


def test_bad_values_are_refused(crm) -> None:
    with pytest.raises(InvalidValue):
        crm.add_contact("Ada", emails=["not-an-address"])
    with pytest.raises(InvalidValue):
        crm.add_contact("Ada", phones=["12"])
    with pytest.raises(NotFound):
        crm.add_contact("Ada", company_id="co9")
    with pytest.raises(InvalidValue):
        crm.add_contact("Ada", tags=["no spaces?"])
    assert crm.list_contacts() == []


def test_tags_are_normalized_on_the_way_in(crm) -> None:
    contact = crm.add_contact("Ada", tags=["VIP", "Trade Show 2026", "vip"])
    assert contact.tags == ["trade-show-2026", "vip"]


def test_update_changes_only_what_is_given(crm) -> None:
    ids = seed(crm)
    contact = crm.update_contact(ids["ada"], title="Countess", owner="kim")
    assert contact.title == "Countess"
    assert contact.owner == "kim"
    assert contact.emails == ["ada@analytical.example"]
    with pytest.raises(InvalidValue):
        crm.update_contact(ids["ada"], status="archived")
    with pytest.raises(NotFound):
        crm.update_contact("c99", title="x")


def test_archived_contacts_drop_out_of_the_list(crm) -> None:
    ids = seed(crm)
    crm.archive_contact(ids["grace"])
    assert [c.id for c in crm.list_contacts()] == [ids["ada"], ids["charles"]]
    assert len(crm.list_contacts(include_archived=True)) == 3
    crm.unarchive_contact(ids["grace"])
    assert len(crm.list_contacts()) == 3


def test_unknown_contacts_are_not_found(crm) -> None:
    with pytest.raises(NotFound):
        crm.contact("c1")


def test_find_by_email_ignores_case(crm) -> None:
    ids = seed(crm)
    assert [c.id for c in crm.find_by_email("ADA@Analytical.example")] == [ids["ada"]]
    assert crm.find_by_email("nobody@example.com") == []


def test_companies(crm) -> None:
    ids = seed(crm)
    with pytest.raises(Exception, match="already"):
        crm.add_company("us navy")
    crm.rename_company(ids["navy"], "United States Navy")
    assert crm.company(ids["navy"]).name == "United States Navy"
    crm.set_primary_contact(ids["navy"], ids["grace"])
    assert crm.company(ids["navy"]).primary_contact_id == ids["grace"]
    with pytest.raises(NotFound):
        crm.set_primary_contact(ids["navy"], "c99")
    assert [c.id for c in crm.companies.members(ids["engines"])] == [ids["ada"]]
