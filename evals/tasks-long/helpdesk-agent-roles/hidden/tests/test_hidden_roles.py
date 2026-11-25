"""Roles on agents, the admin-only operations, and PermissionDenied itself."""

import json

import pytest
from conftest import staff
from deskline import Desk, api, jobs
from deskline.clock import SteppingClock
from deskline.errors import DesklineError, PermissionDenied, ValidationError
from deskline.export import backup, importer
from deskline.services import agents, customers, queues, settings, sla, tickets


def test_an_agent_created_without_a_role_is_an_agent(desk, ctx) -> None:
    agent = agents.create_agent(ctx, "maria", "Maria", "maria@ourdesk.example")
    assert agent.role == "agent"
    lead = agents.create_agent(ctx, "lou", "Lou", "lou@ourdesk.example", role="lead")
    assert lead.role == "lead"
    with pytest.raises(ValidationError):
        agents.create_agent(ctx, "zed", "Zed", "zed@ourdesk.example", role="boss")
    assert "zed" not in desk.store.agents


def test_set_role_is_for_admins(desk, ctx, people, as_) -> None:
    agents.set_role(ctx, "al", "lead")
    assert desk.store.agents["al"].role == "lead"
    agents.set_role(as_("ada"), "al", "viewer")
    assert desk.store.agents["al"].role == "viewer"
    with pytest.raises(PermissionDenied) as caught:
        agents.set_role(as_("lou"), "ana", "admin")
    assert caught.value.permission == "admin"
    assert desk.store.agents["ana"].role == "agent"
    with pytest.raises(ValidationError):
        agents.set_role(ctx, "ana", "superuser")


def test_roles_are_saved(tmp_path) -> None:
    path = tmp_path / "desk.json"
    desk = Desk.create(path, SteppingClock())
    staff(desk)
    again = Desk.open(path, SteppingClock())
    assert {a.id: a.role for a in again.store.agents.values()} == {
        "vic": "viewer", "ana": "agent", "al": "agent", "lou": "lead", "ada": "admin",
    }


def test_files_from_before_roles_load_everyone_as_agent(tmp_path, legacy_file) -> None:
    desk = Desk.open(legacy_file, SteppingClock())
    assert desk.store.agents["maria"].role == "agent"
    assert desk.store.agents["otto"].role == "agent"
    # maria is an agent: she can work her own ticket but not see contact details
    tickets.reply(desk.context("maria"), "T-1", "Fixed?")
    with pytest.raises(PermissionDenied):
        tickets.delete(desk.context("maria"), "T-2")

    path = tmp_path / "v3.json"
    fresh = Desk.create(path, SteppingClock())
    agents.create_agent(fresh.system, "pat", "Pat", "pat@ourdesk.example")
    document = json.loads(path.read_text())
    for agent in document["data"]["agents"]:
        agent.pop("role", None)
    path.write_text(json.dumps(document))
    assert Desk.open(path, SteppingClock()).store.agents["pat"].role == "agent"


def test_permission_denied_is_a_deskline_error(desk, people, as_) -> None:
    with pytest.raises(DesklineError) as caught:
        tickets.create(as_("vic"), people["jane"].id, "Hi", "Hello")
    assert isinstance(caught.value, PermissionDenied)
    assert caught.value.code == "forbidden"
    assert caught.value.permission == "ticket.create"


def test_the_system_may_do_everything(desk, ctx, people) -> None:
    ticket = tickets.create(ctx, people["jane"].id, "Hi", "Hello")
    tickets.assign(ctx, ticket.id, "ana")
    tickets.reply(ctx, ticket.id, "Hello from the system")
    tickets.delete(ctx, ticket.id)
    customers.delete(ctx, people["kim"].id)
    agents.set_role(ctx, "vic", "admin")


@pytest.mark.parametrize(
    "operation",
    [
        lambda c: agents.create_agent(c, "newbie", "Newbie", "newbie@ourdesk.example"),
        lambda c: agents.update_agent(c, "ana", name="Ana Banana"),
        lambda c: agents.set_active(c, "al", False),
        lambda c: agents.create_team(c, "web", "Web people"),
        lambda c: agents.add_member(c, "money", "al"),
        lambda c: agents.remove_member(c, "money", "ana"),
        lambda c: queues.create_queue(c, "web", "Web"),
        lambda c: queues.update_queue(c, "billing", name="Money"),
        lambda c: settings.set_setting(c, "auto_close_days", 9),
        lambda c: backup.dump(c),
        lambda c: jobs.run_all(c),
    ],
)
def test_admin_operations(desk, people, as_, operation) -> None:
    before = desk.store.to_data()
    with pytest.raises(PermissionDenied) as caught:
        operation(as_("lou"))
    assert caught.value.permission == "admin"
    after = desk.store.to_data()
    assert {k: v for k, v in after.items() if k != "audit"} == {
        k: v for k, v in before.items() if k != "audit"
    }
    operation(as_("ada"))


def test_restoring_a_backup_is_for_admins(desk, ctx, people, as_) -> None:
    document = backup.dump(ctx)
    with pytest.raises(PermissionDenied):
        backup.restore(as_("lou"), document)
    backup.restore(as_("ada"), document)


def test_sla_policies_are_for_admins(desk, people, as_) -> None:
    with pytest.raises(PermissionDenied) as caught:
        sla.set_policy(as_("lou"), "urgent", 10, 100)
    assert caught.value.permission == "sla.manage"
    sla.set_policy(as_("ada"), "urgent", 10, 100)
    assert sla.policies(desk.store)[-1].first_response_minutes == 10


def test_customer_permissions(desk, people, as_) -> None:
    with pytest.raises(PermissionDenied) as caught:
        customers.create(as_("vic"), "Nobody")
    assert caught.value.permission == "customer.edit"
    with pytest.raises(PermissionDenied):
        customers.update(as_("vic"), people["bob"].id, organization="Stone Inc")
    created = customers.create(as_("ana"), "Somebody", email="some@body.example")
    customers.update(as_("ana"), created.id, organization="Body Inc")
    with pytest.raises(PermissionDenied) as caught:
        customers.delete(as_("lou"), created.id)
    assert caught.value.permission == "customer.delete"
    customers.delete(as_("ada"), created.id)
    assert customers.get(as_("vic"), people["bob"].id).name == "Bob Stone"
    assert len(customers.list_customers(as_("vic"))) == 3


def test_importing_customers_needs_customer_edit(desk, people, as_) -> None:
    text = "name,email\nNew Person,new@person.example\n"
    with pytest.raises(PermissionDenied):
        importer.import_customers(as_("vic"), text)
    assert importer.import_customers(as_("al"), text).created == ["C-4"]


def test_the_api_shows_and_sets_roles(desk, people) -> None:
    listed = api.dispatch(desk, {"action": "agents.list", "agent": "vic"})["data"]
    assert {a["id"]: a["role"] for a in listed}["lou"] == "lead"
    created = api.dispatch(
        desk,
        {"action": "agents.create", "agent": "ada",
         "params": {"id": "neo", "name": "Neo", "email": "neo@ourdesk.example", "role": "viewer"}},
    )
    assert created["data"]["role"] == "viewer"
    changed = api.dispatch(
        desk, {"action": "agents.set_role", "agent": "ada", "params": {"id": "neo", "role": "lead"}}
    )
    assert changed["ok"] and changed["data"]["role"] == "lead"
    refused = api.dispatch(
        desk, {"action": "agents.set_role", "agent": "lou", "params": {"id": "neo", "role": "admin"}}
    )
    assert refused["error"]["code"] == "forbidden"
    assert desk.store.agents["neo"].role == "lead"
