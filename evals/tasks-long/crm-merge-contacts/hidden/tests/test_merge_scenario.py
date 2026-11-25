"""Random histories of contacts, notes, deals, tags, fields, merges, undos and reopening,
checked after every step against merge_model.Model."""

import random

import pytest
from merge_model import STAGES, Model
from orbit import Crm
from orbit.clock import TickingClock
from orbit.errors import CrmError, NotFound
from orbit.ids import sort_key

FIRST = ["Ada", "Grace", "Alan", "Edsger"]
LAST = ["Lovelace", "Hopper", "Turing", ""]
EMAILS = [f"p{n}@mail.example" for n in range(6)]
TAGS = ["red", "green", "blue"]
LIKES = ["x", "y", "z"]
OPS = ["contact", "note", "deal", "move", "tag", "field", "merge", "undo", "reopen"]
WEIGHTS = [5, 4, 2, 2, 3, 3, 4, 2, 1]


def check(crm: Crm, model: Model, seen: list[str], rng: random.Random) -> None:
    state = model.state
    listed = [c.id for c in crm.list_contacts(include_archived=True)]
    assert listed == sorted(state.contacts, key=sort_key)
    for cid, expected in state.contacts.items():
        contact = crm.contact(cid)
        assert contact.emails == expected["emails"], cid
        assert contact.tags == expected["tags"], cid
        assert contact.fields == expected["fields"], cid
        assert sorted(n.id for n in crm.notes(cid)) == model.notes_of(cid), cid
        assert {e.contact_name for e in crm.timeline(cid)} == {model.name(cid)}, cid
    for sid in seen:
        if model.exists(sid):
            assert crm.contact(sid).id == model.resolve(sid), sid
        else:
            with pytest.raises(NotFound):
                crm.contact(sid)
    for deal_id, expected in state.deals.items():
        deal = crm.deal(deal_id)
        assert deal.contact_ids == expected["contacts"], deal_id
        assert [c.contact_id for c in deal.history()] == expected["history"], deal_id
    assert crm.tag_counts() == model.tag_counts()
    assert crm.duplicates() == model.duplicate_groups(sort_key)
    if state.notes:
        note_id = rng.choice(sorted(state.notes))
        owner, word = state.notes[note_id]
        assert [c.id for c in crm.search(word, include_archived=True)] == [owner]


def pick(rng: random.Random, seen: list[str]) -> str:
    return rng.choice(seen) if seen else "c1"


@pytest.mark.parametrize("seed", range(20))
def test_random_histories(seed: int, tmp_path) -> None:
    rng = random.Random(seed)
    path = tmp_path / "crm.json"
    clock = TickingClock("2026-03-01T09:00:00Z", step=60)
    crm = Crm.open(path, clock=clock)
    crm.define_field("nick")
    crm.define_field("likes", "multi", choices=LIKES)
    model = Model()
    seen: list[str] = []

    for step in range(40):
        op = rng.choices(OPS, WEIGHTS)[0] if len(seen) >= 2 else "contact"
        if op == "contact":
            first = rng.choice(FIRST)
            last = rng.choice(LAST)
            emails = [rng.choice([e, e.upper()]) for e in rng.sample(EMAILS, rng.randint(0, 2))]
            tags = rng.sample(TAGS, rng.randint(0, 2))
            contact = crm.add_contact(first, last, emails=emails, tags=tags)
            assert contact.id not in model.state.merged
            assert contact.id not in model.state.contacts
            model.add_contact(contact.id, first, last, emails, tags, {})
            if contact.id not in seen:
                seen.append(contact.id)
        elif op == "note":
            cid = pick(rng, seen)
            word = f"memo{seed}x{step}z"
            if model.exists(cid):
                note = crm.add_note(cid, f"Talked about {word}")
                model.add_note(note.id, cid, word)
            else:
                with pytest.raises(NotFound):
                    crm.add_note(cid, word)
        elif op == "deal":
            chosen = rng.sample(seen, min(len(seen), rng.randint(1, 3)))
            if all(model.exists(cid) for cid in chosen):
                deal = crm.add_deal(f"Deal {step}", 100 * step, chosen)
                model.add_deal(deal.id, chosen)
            else:
                with pytest.raises(NotFound):
                    crm.add_deal(f"Deal {step}", 100, chosen)
        elif op == "move":
            if not model.state.deals:
                continue
            deal_id = rng.choice(sorted(model.state.deals))
            current = model.state.deals[deal_id]["stage"]
            stage = rng.choice([s for s in STAGES if s != current])
            cid = rng.choice([None, *[s for s in seen if model.exists(s)]])
            crm.move_deal(deal_id, stage, contact_id=cid)
            model.move_deal(deal_id, stage, cid)
        elif op == "tag":
            cid, tag = pick(rng, seen), rng.choice(TAGS)
            if not model.exists(cid):
                with pytest.raises(NotFound):
                    crm.tag(cid, tag)
                continue
            changes = model.would_tag(cid, tag)
            crm.tag(cid, tag)
            if changes:
                model.tag(cid, tag)
        elif op == "field":
            cid = pick(rng, seen)
            if rng.random() < 0.5:
                name, value = "nick", rng.choice(["Ace", "Bee", "Cat"])
            else:
                name, value = "likes", rng.sample(LIKES, rng.randint(1, 3))
            if not model.exists(cid):
                with pytest.raises(NotFound):
                    crm.set_field(cid, name, value)
                continue
            changes = model.would_set(cid, name, value)
            crm.set_field(cid, name, value)
            if changes:
                model.set_field(cid, name, value)
        elif op == "merge":
            keep, other = pick(rng, seen), pick(rng, seen)
            if not (model.exists(keep) and model.exists(other)):
                with pytest.raises(NotFound):
                    crm.merge_contacts(keep, other)
            elif model.resolve(keep) == model.resolve(other):
                with pytest.raises(CrmError):
                    crm.merge_contacts(keep, other)
            else:
                result = crm.merge_contacts(keep, other)
                assert result.id == model.resolve(keep)
                model.merge(keep, other)
        elif op == "undo":
            if not model.undo_stack:
                continue
            crm.undo()
            model.undo()
        elif op == "reopen":
            crm.save()
            crm = Crm.open(path, clock=clock)
        check(crm, model, seen, rng)
