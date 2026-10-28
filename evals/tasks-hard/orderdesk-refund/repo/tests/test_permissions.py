import pytest
from conftest import AUDITOR, CLERK, MANAGER, place, place_and_pay
from orderdesk.commands import COMMANDS
from orderdesk.errors import InvalidState, PermissionDenied
from orderdesk.handlers.cancel import CancelOrder
from orderdesk.handlers.ship import ShipOrder
from orderdesk.permissions import ROLES, Actor, can


def test_clerks_cannot_cancel(app) -> None:
    order_id = place(app)
    with pytest.raises(PermissionDenied):
        app.desk.execute(CancelOrder(order_id, "duplicate"), CLERK)
    assert app.desk.state(order_id).status == "placed"


def test_auditors_only_look(app) -> None:
    order_id = place_and_pay(app)
    with pytest.raises(PermissionDenied):
        app.desk.execute(ShipOrder(order_id, "DHL", "JD1"), AUDITOR)
    assert can(AUDITOR, "reports.view")


def test_unknown_roles_can_do_nothing() -> None:
    assert not can(Actor("eve", "admin"), "orders.view")


def test_managers_can_do_everything_clerks_can() -> None:
    assert ROLES["clerk"] <= ROLES["manager"]


def test_every_command_permission_belongs_to_some_role() -> None:
    held = set().union(*ROLES.values())
    for spec in COMMANDS.values():
        assert spec.permission in held, spec.name


def test_everything_is_audited_whatever_the_outcome(app) -> None:
    order_id = place(app)
    with pytest.raises(PermissionDenied):
        app.desk.execute(CancelOrder(order_id, "duplicate"), CLERK)
    app.desk.execute(CancelOrder(order_id, "duplicate"), MANAGER)
    with pytest.raises(InvalidState):
        app.desk.execute(CancelOrder(order_id, "again"), MANAGER)

    entries = [(e["actor"], e["command"], e["order_id"], e["outcome"]) for e in app.audit.entries()]
    assert entries == [
        ("carla", "place", order_id, "ok"),
        ("carla", "cancel", order_id, "denied"),
        ("mo", "cancel", order_id, "ok"),
        ("mo", "cancel", order_id, "rejected"),
    ]
    assert app.audit.entries()[2]["details"] == {"reason": "duplicate"}
