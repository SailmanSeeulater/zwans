import json
from dataclasses import replace

import pytest
from conftest import seed
from orbit.errors import InvalidValue, NotFound
from orbit.jobs.dispatcher import deliver, sign


def events(crm) -> list[str]:
    return [message.event for message in crm.outbox()]


def test_changes_queue_messages_for_subscribers(crm) -> None:
    hook = crm.subscribe("https://hooks.example/all")
    ids = seed(crm)
    queued = events(crm)
    assert queued.count("contact.created") == 3
    assert queued.count("deal.created") == 2
    assert "deal.stage_changed" in queued
    assert {m.subscription_id for m in crm.outbox()} == {hook.id}
    assert ids


def test_subscriptions_pick_events(crm) -> None:
    crm.subscribe("https://hooks.example/deals", events=["deal.created", "deal.stage_changed"])
    seed(crm)
    assert events(crm) == ["deal.created", "deal.created", "deal.stage_changed"]
    with pytest.raises(InvalidValue):
        crm.subscribe("https://hooks.example/x", events=["contact.exploded"])
    with pytest.raises(InvalidValue):
        crm.subscribe("ftp://hooks.example/x")


def test_a_subscription_can_follow_one_contact(crm) -> None:
    ids = seed(crm)
    crm.subscribe("https://hooks.example/charles", contact_id=ids["charles"])
    crm.add_note(ids["ada"], "Not about Charles")
    crm.add_note(ids["charles"], "About Charles")
    crm.move_deal(ids["engine"], "proposal")
    assert events(crm) == ["note.added", "deal.stage_changed"]
    with pytest.raises(NotFound):
        crm.subscribe("https://hooks.example/x", contact_id="c99")


def test_payload_shapes(crm) -> None:
    crm.subscribe("https://hooks.example/all")
    ids = seed(crm)
    crm.update_contact(ids["grace"], title="Rear Admiral")
    created, *_, updated = [m for m in crm.outbox() if m.event.startswith("contact.")]
    assert created.payload["contact"]["id"] == ids["ada"]
    assert created.payload["contact"]["company"] == {
        "id": ids["engines"],
        "name": "Analytical Engines",
    }
    assert updated.payload["changed"] == ["title"]
    assert updated.payload["contact"]["title"] == "Rear Admiral"
    stage = next(m for m in crm.outbox() if m.event == "deal.stage_changed")
    assert stage.payload["from"] == "lead"
    assert stage.payload["deal"]["contact_ids"] == [ids["ada"], ids["charles"]]


def test_delivery_signs_retries_and_gives_up(crm) -> None:
    crm.subscribe("https://hooks.example/a", events=["note.added"], secret="s3cret")
    ids = seed(crm)
    sent = []

    def ok(url, body, headers):
        sent.append((url, body, headers))
        return 204

    report = deliver(crm, ok)
    assert len(report.delivered) == 1
    url, body, headers = sent[0]
    assert headers["X-Orbit-Signature"] == sign("s3cret", body)
    assert json.loads(body)["data"]["body"] == "Wants a quote for the difference engine"
    assert crm.outbox(pending_only=True) == []

    crm.add_note(ids["grace"], "Second")

    def down(url, body, headers):
        raise OSError("connection refused")

    crm.settings = replace(crm.settings, retry_after_seconds=3600)
    assert deliver(crm, down).retrying
    assert deliver(crm, ok).delivered == []  # not due yet
    crm.settings = replace(crm.settings, outbox_max_attempts=2, retry_after_seconds=0)
    crm.webhooks.save_message(replace(crm.outbox()[-1], next_attempt_at=None))
    assert deliver(crm, down).failed
    assert crm.outbox(pending_only=True) == []
