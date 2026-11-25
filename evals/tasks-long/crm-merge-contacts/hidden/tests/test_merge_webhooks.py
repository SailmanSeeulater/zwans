"""The webhook events a merge sends."""

from conftest import world
from orbit.payloads import contact_payload


def messages(crm, subscription_id: str) -> list:
    return [m for m in crm.outbox() if m.subscription_id == subscription_id]


def test_a_merge_sends_deal_updates_then_contact_merged(crm) -> None:
    ids = world(crm)
    hook = crm.subscribe("https://hooks.example/all")
    crm.merge_contacts(ids["a"], ids["b"])
    sent = messages(crm, hook.id)
    assert [m.event for m in sent] == ["deal.updated", "deal.updated", "contact.merged"]
    assert [m.payload["id"] for m in sent[:2]] == [ids["d1"], ids["d2"]]
    assert sent[0].payload["contact_ids"] == [ids["charles"], ids["a"]]
    assert sent[1].payload["contact_ids"] == [ids["a"], ids["charles"]]


def test_the_merged_payload(crm) -> None:
    ids = world(crm)
    hook = crm.subscribe("https://hooks.example/all", events=["contact.merged"])
    crm.merge_contacts(ids["a"], ids["b"])
    (message,) = messages(crm, hook.id)
    assert message.event == "contact.merged"
    assert message.payload == {
        "contact": contact_payload(crm.contact(ids["a"]), crm.company(ids["engines"])),
        "merged_id": ids["b"],
    }
    contact = message.payload["contact"]
    assert contact["id"] == ids["a"]
    assert contact["tags"] == ["looms", "vip"]
    assert contact["emails"] == ["ada@analytical.example", "countess@home.example"]
    assert contact["fields"]["nickname"] == "Enchantress"


def test_no_contact_updated_or_other_events(crm) -> None:
    ids = world(crm)
    hook = crm.subscribe("https://hooks.example/all")
    crm.merge_contacts(ids["grace"], ids["twin"])
    assert [m.event for m in messages(crm, hook.id)] == ["contact.merged"]


def test_subscriptions_following_b_get_the_merge_and_what_follows(crm) -> None:
    ids = world(crm)
    follower = crm.subscribe("https://hooks.example/b", contact_id=ids["b"])
    crm.merge_contacts(ids["a"], ids["b"])
    crm.add_note(ids["a"], "After the merge")
    assert [m.event for m in messages(crm, follower.id)] == [
        "deal.updated",
        "deal.updated",
        "contact.merged",
        "note.added",
    ]


def test_contact_merged_is_about_a(crm) -> None:
    ids = world(crm)
    follows_a = crm.subscribe(
        "https://hooks.example/a", events=["contact.merged"], contact_id=ids["a"]
    )
    follows_c = crm.subscribe(
        "https://hooks.example/c", events=["contact.merged"], contact_id=ids["charles"]
    )
    crm.merge_contacts(ids["a"], ids["b"])
    assert [m.event for m in messages(crm, follows_a.id)] == ["contact.merged"]
    assert messages(crm, follows_c.id) == []


def test_undoing_a_merge_sends_nothing(crm) -> None:
    ids = world(crm)
    crm.subscribe("https://hooks.example/all")
    crm.merge_contacts(ids["a"], ids["b"])
    queued = len(crm.outbox())
    crm.undo()
    assert len(crm.outbox()) == queued
