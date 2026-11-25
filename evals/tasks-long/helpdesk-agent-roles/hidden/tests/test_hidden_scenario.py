"""Random histories: every operation, by every role, checked against the README's table.

After each step: an operation the table forbids must raise PermissionDenied naming one of
the missing permissions, change nothing, and leave exactly one `permission.denied` entry;
an operation it allows must go through. Every so often, what each agent sees through
search, the API and the exports must contain contact details exactly when their role has
contact.view.
"""

import random

import oracle
import pytest
from conftest import ROLE_OF, leaks, staff
from deskline import Desk, api, auditview, search
from deskline.clock import SteppingClock
from deskline.errors import PermissionDenied
from deskline.export import csv_export
from deskline.models import TRANSITIONS
from deskline.services import agents, bulk, macros, merging, tickets

ACTORS = [None, *ROLE_OF]
MACROS = [
    ("Note", [{"type": "note", "value": "Seen by {{ recipient.name }}"}]),
    ("Bump", [{"type": "add_tag", "value": "bumped"}, {"type": "set_priority", "value": "high"}]),
    ("Grab", [{"type": "assign_self"}, {"type": "add_tag", "value": "grabbed"}]),
    ("Answer", [{"type": "note", "value": "Answering"}, {"type": "reply", "value": "Hello {{ customer.name }}"}]),
    ("To Al", [{"type": "add_tag", "value": "for-al"}, {"type": "assign", "value": "al"}]),
    ("To Lou", [{"type": "assign", "value": "lou"}, {"type": "note", "value": "Lou has it"}]),
]


def snapshot(desk) -> dict:
    data = desk.store.to_data()
    data.pop("audit")
    return data


class World:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.desk = Desk.memory(SteppingClock("2026-03-02T09:00:00Z"))
        self.people = staff(self.desk)
        self.roles = dict(ROLE_OF)
        system = self.desk.system
        self.macros = [macros.create_macro(system, name, actions) for name, actions in MACROS]
        for _ in range(6):
            self.new_ticket(system)
        for ticket in self.active():
            choice = self.rng.choice([None, "ana", "al", "lou"])
            if choice:
                tickets.assign(system, ticket.id, choice)

    def new_ticket(self, ctx):
        customer = self.rng.choice(list(self.people.values()))
        return tickets.create(ctx, customer.id, f"Problem {self.rng.randint(1, 999)}", "Help me")

    def active(self):
        return [t for t in self.desk.store.tickets.values() if t.status != "closed" and not t.merged_into]

    def ctx(self, actor):
        return self.desk.context(actor)

    def role(self, actor):
        return None if actor is None else self.roles[actor]

    def plan(self, actor):
        """Pick an operation: (description, needs, callable, denial target or None)."""
        rng = self.rng
        tickets_now = self.active()
        ticket = rng.choice(tickets_now)
        ctx = self.ctx(actor)
        kind = rng.choice(
            ["reply", "note", "status", "priority", "tag", "take", "assign", "unassign",
             "macro", "macro", "bulk", "bulk", "merge", "create", "role", "export", "audit",
             "contact-search"]
        )
        who = ticket.assignee
        if kind == "reply":
            return kind, [("ticket.edit", who)], lambda: tickets.reply(ctx, ticket.id, "Hi"), ticket.id
        if kind == "note":
            return kind, [("ticket.note", who)], lambda: tickets.note(ctx, ticket.id, "Hm"), ticket.id
        if kind == "status":
            choices = [s for s in TRANSITIONS[ticket.status] if s != "closed"]
            if not choices:
                return self.plan(actor)
            status = rng.choice(choices)
            return f"status {status}", [("ticket.edit", who)], lambda: tickets.set_status(ctx, ticket.id, status), ticket.id
        if kind == "priority":
            priority = rng.choice(["low", "normal", "high", "urgent"])
            return kind, [("ticket.edit", who)], lambda: tickets.set_priority(ctx, ticket.id, priority), ticket.id
        if kind == "tag":
            return kind, [("ticket.edit", who)], lambda: tickets.add_tag(ctx, ticket.id, rng.choice(["a", "b"])), ticket.id
        if kind == "take":
            if actor is None:
                return self.plan(actor)
            return kind, [("ticket.edit", who)], lambda: tickets.take(ctx, ticket.id), ticket.id
        if kind == "assign":
            to = rng.choice(list(ROLE_OF))
            perm = oracle.assign_permission(actor, to)
            return f"assign {to}", [(perm, who)], lambda: tickets.assign(ctx, ticket.id, to), ticket.id
        if kind == "unassign":
            return kind, [("ticket.assign", who)], lambda: tickets.assign(ctx, ticket.id, None), ticket.id
        if kind == "macro":
            macro = rng.choice(self.macros)
            if actor is None and any(a["type"] == "assign_self" for a in macro.actions):
                return self.plan(actor)
            needs = [("macro.run", None)]
            current = who
            for action in macro.actions:
                if action["type"] == "note":
                    needs.append(("ticket.note", current))
                elif action["type"] == "assign":
                    needs.append((oracle.assign_permission(actor, action["value"]), current))
                    current = action["value"]
                elif action["type"] == "assign_self":
                    needs.append(("ticket.edit", current))
                    current = actor
                else:
                    needs.append(("ticket.edit", current))
            return f"macro {macro.name}", needs, lambda: macros.apply_macro(ctx, macro.id, ticket.id), None
        if kind == "bulk":
            chosen = rng.sample(tickets_now, k=min(len(tickets_now), rng.randint(1, 3)))
            changes = {}
            if rng.random() < 0.5:
                changes["priority"] = rng.choice(["low", "high"])
            if rng.random() < 0.4:
                changes["add_tags"] = ["bulk"]
            if rng.random() < 0.4 or not changes:
                changes["assignee"] = rng.choice(["", *ROLE_OF])
            needs = []
            for t in chosen:
                if "assignee" in changes:
                    needs.append((oracle.assign_permission(actor, changes["assignee"] or None), t.assignee))
                if set(changes) - {"assignee"}:
                    needs.append(("ticket.edit", t.assignee))
            ids = [t.id for t in chosen]
            return f"bulk {ids} {changes}", needs, lambda: bulk.bulk_update(ctx, ids, changes), None
        if kind == "merge":
            if len(tickets_now) < 3:
                return self.plan(actor)
            source, target = rng.sample(tickets_now, 2)
            needs = [("ticket.edit", source.assignee), ("ticket.edit", target.assignee)]
            return f"merge {source.id}->{target.id}", needs, lambda: merging.merge(ctx, source.id, target.id), None
        if kind == "create":
            return kind, [("ticket.create", None)], lambda: self.new_ticket(ctx), None
        if kind == "role":
            agent_id = rng.choice(list(ROLE_OF))
            role = rng.choice(["viewer", "agent", "lead", "admin"])

            def change():
                agents.set_role(ctx, agent_id, role)
                self.roles[agent_id] = role

            return f"role {agent_id}={role}", [("admin", None)], change, None
        if kind == "export":
            return kind, [("export", None)], lambda: csv_export.tickets_csv(ctx), None
        if kind == "audit":
            return kind, [("audit.view", None)], lambda: auditview.entries(ctx, limit=5), None
        return kind, [("contact.view", None)], lambda: search.run(ctx, "email:example"), None

    def check_visibility(self) -> None:
        some = sorted(self.desk.store.tickets)[0]
        for actor, role in self.roles.items():
            ctx = self.ctx(actor)
            outputs = [
                search.run(ctx, ""),
                api.dispatch(self.desk, {"action": "tickets.get", "agent": actor, "params": {"id": some}}),
                api.dispatch(self.desk, {"action": "customers.list", "agent": actor}),
            ]
            if role != "viewer":
                outputs.append(csv_export.customers_csv(ctx))
            sees = role in oracle.LEADS
            assert bool(leaks(outputs)) == sees, (actor, role)


@pytest.mark.parametrize("seed", range(8))
def test_random_histories(seed) -> None:
    world = World(seed)
    store = world.desk.store
    for step in range(220):
        if not world.active():
            world.new_ticket(world.desk.system)
        actor = world.rng.choice(ACTORS)
        role = world.role(actor)
        description, needs, run, target = world.plan(actor)
        lacking = oracle.missing(role, actor, needs)
        before = snapshot(world.desk)
        entries = len(store.audit)
        where = f"seed {seed} step {step}: {actor} ({role}) {description}"
        try:
            run()
        except PermissionDenied as exc:
            assert lacking, f"{where}: refused ({exc.permission}) but the table allows it"
            assert exc.permission in lacking, f"{where}: refused for {exc.permission}, missing {lacking}"
            assert snapshot(world.desk) == before, f"{where}: a refused operation changed something"
            assert len(store.audit) == entries + 1, where
            entry = store.audit[-1]
            assert (entry.action, entry.actor) == ("permission.denied", actor), where
            assert entry.details["permission"] == exc.permission, where
            if target is not None:
                assert entry.target == target, where
        else:
            assert not lacking, f"{where}: allowed, but the table says it needs {lacking}"
        if step % 30 == 29:
            world.check_visibility()
    world.check_visibility()
