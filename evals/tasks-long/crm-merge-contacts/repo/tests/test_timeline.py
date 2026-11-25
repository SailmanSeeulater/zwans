from conftest import seed


def kinds(entries) -> list[str]:
    return [entry.kind for entry in entries]


def test_the_timeline_records_what_happened(crm) -> None:
    ids = seed(crm)
    assert kinds(crm.timeline(ids["ada"])) == ["created", "note", "email", "task", "deal", "stage"]
    assert kinds(crm.timeline(ids["charles"])) == ["created", "deal", "stage"]
    stage = crm.timeline(ids["ada"])[-1]
    assert stage.summary == "Difference engine: lead -> qualified"
    assert stage.ref == ids["engine"]


def test_entries_show_the_contacts_name(crm) -> None:
    ids = seed(crm)
    assert {e.contact_name for e in crm.timeline(ids["ada"])} == {"Ada Lovelace"}


def test_renaming_a_contact_renames_their_entries(crm) -> None:
    ids = seed(crm)
    crm.update_contact(ids["ada"], last_name="King")
    entries = crm.timeline(ids["ada"])
    assert {e.contact_name for e in entries} == {"Ada King"}
    assert entries[-1].kind == "updated"
    assert entries[-1].summary == "Changed last_name"


def test_other_changes_leave_names_alone(crm) -> None:
    ids = seed(crm)
    crm.tag(ids["grace"], "navy")
    assert [e.summary for e in crm.timeline(ids["grace"])][-1] == "Changed tags"


def test_the_timeline_can_be_limited(crm) -> None:
    ids = seed(crm)
    assert kinds(crm.timeline(ids["ada"], limit=2)) == ["deal", "stage"]


def test_a_contact_without_history_has_an_almost_empty_timeline(crm) -> None:
    contact = crm.add_contact("New")
    assert kinds(crm.timeline(contact.id)) == ["created"]
