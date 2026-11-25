import json

from deskline import api


def call(desk, action, agent=None, **params):
    request = {"action": action, "params": params}
    if agent is not None:
        request["agent"] = agent
    return api.dispatch(desk, request)


def test_creating_and_reading_a_ticket(desk, seeded) -> None:
    created = call(desk, "tickets.create", customer="C-1", subject="Printer", body="It jams")
    assert created["ok"]
    assert created["data"]["id"] == "T-1"
    got = call(desk, "tickets.get", id="T-1")["data"]
    assert got["requester"]["name"] == "Jane Doe"
    assert got["requester"]["email"] == "jane@example.org"
    assert got["comments"][0]["body"] == "It jams"


def test_an_agent_takes_and_answers(desk, seeded) -> None:
    call(desk, "tickets.create", customer="C-1", subject="Printer", body="It jams")
    assert call(desk, "tickets.take", "maria", id="T-1")["data"]["assignee"] == "maria"
    data = call(desk, "tickets.reply", "maria", id="T-1", body="On it")["data"]
    assert data["status"] == "open"
    assert data["comments"][-1]["author"] == "maria"


def test_updates_in_one_request(desk, seeded) -> None:
    call(desk, "tickets.create", customer="C-1", subject="Printer", body="It jams")
    data = call(desk, "tickets.update", id="T-1", priority="urgent", add_tags=["hw"], status="pending")["data"]
    assert (data["priority"], data["tags"], data["status"]) == ("urgent", ["hw"], "pending")


def test_errors_come_back_with_codes(desk, seeded) -> None:
    assert call(desk, "tickets.get", id="T-9")["error"]["code"] == "not_found"
    assert call(desk, "tickets.create", customer="C-1", subject="", body="x")["error"]["code"] == "invalid"
    assert call(desk, "nope.nothing")["error"]["code"] == "unknown_action"
    assert call(desk, "tickets.get", "ghost", id="T-1")["error"]["code"] == "not_found"


def test_customers_and_search(desk, seeded) -> None:
    call(desk, "tickets.create", customer="C-2", subject="Refund", body="Double charge")
    customer = call(desk, "customers.get", id="C-2")["data"]
    assert customer["tickets"] == ["T-1"]
    assert customer["phone"] == "+44 20 7946 0000"
    rows = call(desk, "tickets.search", query="refund")["data"]
    assert rows[0]["requester_email"] == "bob@stone.example"
    listed = call(desk, "customers.list", text="stone")["data"]
    assert [c["id"] for c in listed] == ["C-2"]


def test_macros_and_saved_searches(desk, seeded) -> None:
    call(desk, "tickets.create", customer="C-1", subject="Printer", body="It jams")
    macro = call(desk, "macros.create", name="Hold", actions=[{"type": "set_status", "value": "pending"}])["data"]
    data = call(desk, "macros.apply", macro=macro["id"], ticket="T-1")["data"]
    assert data["status"] == "pending"
    saved = call(desk, "searches.save", "maria", name="Waiting", query="status:pending")["data"]
    result = call(desk, "searches.run", "maria", id=saved["id"])["data"]
    assert result["count"] == 1


def test_reports_audit_and_export(desk, seeded) -> None:
    call(desk, "tickets.create", customer="C-1", subject="Printer", body="It jams")
    assert call(desk, "reports.sla")["data"]["by_priority"]["normal"]["tickets"] == 1
    entries = call(desk, "audit.list", target="T-1")["data"]
    assert entries[0]["action"] == "ticket.created"
    csv_text = call(desk, "export.tickets")["data"]["csv"]
    assert "jane@example.org" in csv_text


def test_json_in_json_out(desk, seeded) -> None:
    out = json.loads(api.handle_json(desk, json.dumps({"action": "agents.list"})))
    assert [a["id"] for a in out["data"]] == ["maria", "tom"]
    assert json.loads(api.handle_json(desk, "{nope"))["error"]["code"] == "invalid"
