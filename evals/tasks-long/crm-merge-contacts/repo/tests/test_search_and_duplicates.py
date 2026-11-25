from conftest import seed
from orbit.jobs.reindex import check_indexes


def ids_of(contacts) -> list[str]:
    return [c.id for c in contacts]


def test_search_by_name_address_company_and_prefix(crm) -> None:
    ids = seed(crm)
    assert ids_of(crm.search("lovelace")) == [ids["ada"]]
    assert ids_of(crm.search("analytical")) == [ids["ada"], ids["charles"]]
    assert ids_of(crm.search("ada analytical")) == [ids["ada"]]
    assert ids_of(crm.search("hop")) == [ids["grace"]]
    assert crm.search("nobody") == []
    assert crm.search("") == []


def test_search_reads_notes_emails_tags_and_fields(crm) -> None:
    ids = seed(crm)
    crm.define_field("interests", "multi", choices=["looms", "engines"])
    crm.set_field(ids["grace"], "interests", ["looms"])
    assert ids_of(crm.search("difference")) == [ids["ada"]]
    assert ids_of(crm.search("attached")) == [ids["ada"]]
    assert ids_of(crm.search("vip")) == [ids["ada"]]
    assert ids_of(crm.search("looms")) == [ids["grace"]]


def test_search_follows_changes(crm) -> None:
    ids = seed(crm)
    crm.update_contact(ids["grace"], last_name="Murray")
    assert crm.search("hopper") == []
    assert ids_of(crm.search("murray")) == [ids["grace"]]
    crm.rename_company(ids["navy"], "Fleet Command")
    assert ids_of(crm.search("fleet")) == [ids["grace"]]
    crm.add_note(ids["charles"], "Mentioned the analytical engine")
    assert ids_of(crm.search("mentioned")) == [ids["charles"]]


def test_archived_contacts_are_only_found_when_asked(crm) -> None:
    ids = seed(crm)
    crm.archive_contact(ids["grace"])
    assert crm.search("hopper") == []
    assert ids_of(crm.search("hopper", include_archived=True)) == [ids["grace"]]


def test_duplicates_by_email_phone_and_name(crm) -> None:
    ids = seed(crm)
    same_email = crm.add_contact("A.", "L.", emails=["ADA@analytical.example"])
    same_phone = crm.add_contact("Augusta", phones=["020 7946 0000"])
    same_name = crm.add_contact("grace", "HOPPER")
    assert crm.duplicates() == [
        (ids["ada"], same_email.id, same_phone.id),
        (ids["grace"], same_name.id),
    ]
    assert crm.duplicates_of(ids["grace"]) == [same_name.id]
    assert crm.dedupe.reasons(ids["ada"], same_phone.id) == ["phone"]


def test_archived_contacts_are_not_duplicates(crm) -> None:
    ids = seed(crm)
    twin = crm.add_contact("Grace", "Hopper")
    crm.archive_contact(twin.id)
    assert crm.duplicates() == []
    assert ids["grace"]


def test_indexes_match_the_data_after_changes(crm) -> None:
    ids = seed(crm)
    crm.tag(ids["grace"], "navy")
    crm.update_contact(ids["ada"], emails=["countess@lovelace.example"])
    assert check_indexes(crm) == []
