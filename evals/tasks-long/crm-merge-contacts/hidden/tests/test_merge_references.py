"""Everything that pointed at B points at A after a merge."""

from conftest import world


def setup(crm) -> dict[str, str]:
    ids = world(crm)
    crm.merge_contacts(ids["a"], ids["b"])
    return ids


def test_notes_tasks_and_emails_move_to_a(crm) -> None:
    ids = setup(crm)
    assert [n.body for n in crm.notes(ids["a"])] == [
        "Wants a quote for the difference engine",
        "Collects punched cards",
    ]
    assert sorted(t.title for t in crm.tasks(ids["a"])) == [
        "Call back about the quote",
        "Send the loom catalogue",
    ]
    assert [e.subject for e in crm.emails(ids["a"])] == ["Quote attached", "Loom pattern samples"]
    assert {t.contact_id for t in crm.tasks()} <= {ids["a"]}


def test_a_deal_with_both_lists_a_once_in_its_own_place(crm) -> None:
    ids = setup(crm)
    assert crm.deal(ids["d1"]).contact_ids == [ids["charles"], ids["a"]]


def test_a_takes_bs_place_on_a_deal(crm) -> None:
    ids = setup(crm)
    assert crm.deal(ids["d2"]).contact_ids == [ids["a"], ids["charles"]]
    assert crm.deal(ids["d3"]).contact_ids == [ids["grace"]]


def test_stage_history_points_at_a(crm) -> None:
    ids = setup(crm)
    assert [c.contact_id for c in crm.deal(ids["d2"]).history()] == [None, ids["a"]]
    assert [c.contact_id for c in crm.deal(ids["d1"]).history()] == [None, ids["charles"]]


def test_deals_are_found_from_a(crm) -> None:
    ids = setup(crm)
    assert [d.id for d in crm.deals.for_contact(ids["a"])] == [ids["d1"], ids["d2"]]


def test_companies_whose_primary_contact_was_b(crm) -> None:
    ids = setup(crm)
    assert crm.company(ids["navy"]).primary_contact_id == ids["a"]


def test_bs_timeline_entries_belong_to_a_and_show_as_name(crm) -> None:
    ids = world(crm)
    a_entries = len(crm.timeline(ids["a"]))
    b_entries = len(crm.timeline(ids["b"]))
    crm.merge_contacts(ids["a"], ids["b"])
    entries = crm.timeline(ids["a"])
    assert len(entries) == a_entries + b_entries + 1
    assert {e.contact_name for e in entries} == {"Ada Lovelace"}
    assert {e.contact_id for e in entries} == {ids["a"]}
    assert "Collects punched cards" in [e.summary for e in entries]


def test_the_merge_adds_one_merged_entry(crm) -> None:
    ids = setup(crm)
    merged = [e for e in crm.timeline(ids["a"]) if e.kind == "merged"]
    assert len(merged) == 1
    assert merged[0].ref == ids["b"]
    assert crm.timeline(ids["a"])[-1].kind == "merged"


def test_timeline_entries_from_both_sides_are_in_time_order(crm) -> None:
    ids = setup(crm)
    stamps = [e.at for e in crm.timeline(ids["a"])]
    assert stamps == sorted(stamps)


def test_subscriptions_following_b_follow_a(crm) -> None:
    ids = world(crm)
    sub = crm.subscribe("https://hooks.example/b", contact_id=ids["b"])
    crm.merge_contacts(ids["a"], ids["b"])
    assert {s.id: s.contact_id for s in crm.subscriptions()} == {sub.id: ids["a"]}


def test_other_contacts_are_untouched(crm) -> None:
    ids = world(crm)
    before = crm.contact(ids["grace"]), crm.timeline(ids["grace"]), crm.notes(ids["charles"])
    crm.merge_contacts(ids["a"], ids["b"])
    after = crm.contact(ids["grace"]), crm.timeline(ids["grace"]), crm.notes(ids["charles"])
    assert before == after
