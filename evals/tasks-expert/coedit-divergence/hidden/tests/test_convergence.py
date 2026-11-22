"""Replicas that applied the same ops show the same text, the text the README defines, and a
replica's own edits land where it put them, whatever the network does."""

import random

import pytest
from oracle import text_of

from coedit import Delete, Insert, Op, Replica


def check_own_insert(replica: Replica, index: int, char: str) -> Insert:
    before = replica.text()
    op = replica.insert(index, char)
    assert replica.text() == before[:index] + char + before[index:]
    return op


def check_own_delete(replica: Replica, index: int) -> Delete:
    before = replica.text()
    op = replica.delete(index)
    assert replica.text() == before[:index] + before[index + 1 :]
    return op


# -- the network


def test_an_insert_that_arrives_before_the_character_it_follows_waits_for_it() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    ops = [ann.insert(index, char) for index, char in enumerate("abc")]

    for op in reversed(ops):
        bob.apply(op)

    assert bob.text() == "abc"


def test_a_chain_of_waiting_inserts_all_arrive_once_the_first_does() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    ops = [ann.insert(index, char) for index, char in enumerate("waiting")]
    rng = random.Random(4)
    rest = ops[1:]
    rng.shuffle(rest)

    for op in rest:
        bob.apply(op)
    assert bob.text() == ""
    bob.apply(ops[0])

    assert bob.text() == "waiting"


def test_a_delete_that_arrives_before_its_character_takes_effect_when_it_comes() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    typed = [ann.insert(index, char) for index, char in enumerate("cart")]
    removed = ann.delete(3)

    bob.apply(removed)
    for op in typed:
        bob.apply(op)

    assert bob.text() == "car"


def test_an_op_that_arrives_twice_counts_once() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    first = ann.insert(0, "a")
    second = ann.insert(1, "b")

    bob.apply(second)  # waits for the first...
    bob.apply(second)  # ...and so does its repeat
    bob.apply(first)
    bob.apply(first)
    bob.apply(second)

    assert bob.text() == "ab"


def test_applying_your_own_op_again_changes_nothing() -> None:
    ann = Replica("ann")
    ops = [ann.insert(index, char) for index, char in enumerate("echo")]
    ops.append(ann.delete(0))

    for op in ops:
        ann.apply(op)

    assert ann.text() == "cho"


def test_a_deleted_character_can_still_be_typed_after() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    first = [ann.insert(index, char) for index, char in enumerate("ab")]
    for op in first:
        bob.apply(op)
    gone = ann.delete(1)  # ann deletes the b...
    after_b = bob.insert(2, "c")  # ...while bob types after it

    ann.apply(after_b)
    bob.apply(gone)

    assert ann.text() == bob.text() == "ac"


# -- the order of the text


def test_children_of_the_same_character_come_newest_first() -> None:
    replica = Replica("ann")
    replica.apply(Insert(id=(1, "ann"), after=None, char="a"))
    replica.apply(Insert(id=(2, "bob"), after=(1, "ann"), char="b"))
    replica.apply(Insert(id=(5, "cy"), after=(1, "ann"), char="c"))
    replica.apply(Insert(id=(3, "dee"), after=(1, "ann"), char="d"))

    assert replica.text() == "acdb"


def test_equal_counters_put_the_higher_site_first() -> None:
    first, second = Replica("ann"), Replica("bob")
    ops: list[Op] = [
        Insert(id=(1, "ann"), after=None, char="a"),
        Insert(id=(2, "ann"), after=(1, "ann"), char="x"),
        Insert(id=(2, "bob"), after=(1, "ann"), char="y"),
    ]
    for op in ops:
        first.apply(op)
    for op in reversed(ops):
        second.apply(op)

    assert first.text() == second.text() == "ayx"


def test_a_character_older_than_the_one_it_follows_still_comes_right_after_it() -> None:
    # Imported text: b's counter is lower than a's, and c (older than a) also starts the text.
    ops: list[Op] = [
        Insert(id=(5, "imp"), after=None, char="a"),
        Insert(id=(1, "imp"), after=(5, "imp"), char="b"),
        Insert(id=(3, "imp"), after=None, char="c"),
    ]
    for order in ([0, 1, 2], [2, 0, 1], [2, 1, 0], [1, 2, 0]):
        replica = Replica("ann")
        for index in order:
            replica.apply(ops[index])
        assert replica.text() == "abc", order


def test_a_whole_subtree_comes_before_the_next_sibling() -> None:
    ops: list[Op] = [
        Insert(id=(9, "imp"), after=None, char="x"),
        Insert(id=(2, "imp"), after=None, char="z"),
        Insert(id=(1, "old"), after=(9, "imp"), char="y"),
        Insert(id=(1, "zz"), after=(1, "old"), char="Y"),
        Insert(id=(7, "imp"), after=(2, "imp"), char="!"),
    ]
    rng = random.Random(1)
    for _ in range(30):
        shuffled = ops[:]
        rng.shuffle(shuffled)
        replica = Replica("ann")
        for op in shuffled:
            replica.apply(op)
        assert replica.text() == "xyYz!"


# -- a replica's own edits


def test_typing_lands_at_the_index_after_seeing_much_newer_characters() -> None:
    bob = Replica("bob")
    bob.apply(Insert(id=(50, "imp"), after=None, char="b"))
    bob.apply(Insert(id=(40, "imp"), after=(50, "imp"), char="c"))

    check_own_insert(bob, 0, "a")
    check_own_insert(bob, 1, "-")
    check_own_insert(bob, 4, "d")

    assert bob.text() == "a-bcd"


def test_indexes_count_only_the_characters_that_show() -> None:
    ann = Replica("ann")
    for index, char in enumerate("abcdef"):
        check_own_insert(ann, index, char)
    check_own_delete(ann, 1)
    check_own_delete(ann, 1)

    check_own_insert(ann, 2, "X")
    check_own_delete(ann, 3)

    assert ann.text() == "adXf"


def test_a_long_text_typed_in_one_go() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    text = "".join(random.Random(2).choice("abcdefgh ") for _ in range(2500))
    ops = [ann.insert(index, char) for index, char in enumerate(text)]
    for op in ops:
        bob.apply(op)

    assert ann.text() == bob.text() == text


# -- many people, a bad network, and an importer with ids of its own


def simulate(seed: int, importer: bool) -> None:
    rng = random.Random(seed)
    people = [Replica(site) for site in rng.sample(["ann", "bob", "cy", "dee", "eve"], 3)]
    sent: list[Op] = []
    own: list[list[Op]] = [[] for _ in people]
    got: list[list[Op]] = [[] for _ in people]
    in_flight: list[tuple[int, Op]] = []
    inserted: list[Insert] = []

    def send(op: Op, sender: int | None) -> None:
        sent.append(op)
        for index in range(len(people)):
            copies = 2 if rng.random() < 0.15 else 1
            if index == sender:
                copies = 1 if rng.random() < 0.2 else 0
            in_flight.extend((index, op) for _ in range(copies))

    def deliver(position: int) -> None:
        index, op = in_flight.pop(position)
        people[index].apply(op)
        got[index].append(op)

    for step in range(rng.randint(150, 300)):
        roll = rng.random()
        if roll < 0.4:
            who = rng.randrange(len(people))
            person = people[who]
            length = len(person.text())
            if length and rng.random() < 0.3:
                op: Op = check_own_delete(person, rng.randrange(length))
            else:
                op = check_own_insert(person, rng.randint(0, length), rng.choice("abcxyz"))
                inserted.append(op)
            own[who].append(op)
            send(op, who)
        elif roll < 0.52 and importer:
            if inserted and rng.random() < 0.2:
                send(Delete(target=rng.choice(inserted).id), None)
            else:
                after = rng.choice(inserted).id if inserted and rng.random() < 0.85 else None
                op = Insert(id=(rng.randint(1, 30), f"imp{step}"), after=after, char="I")
                inserted.append(op)
                send(op, None)
        elif in_flight:
            # Mostly the newest messages: ops overtake the ones they depend on.
            position = len(in_flight) - 1 - min(int(rng.expovariate(0.3)), len(in_flight) - 1)
            deliver(position)
        if step % 20 == 0:
            for index, person in enumerate(people):
                assert person.text() == text_of(own[index] + got[index]), (seed, step)

    while in_flight:
        deliver(rng.randrange(len(in_flight)))
    expected = text_of(sent)
    for person in people:
        assert person.text() == expected, seed


@pytest.mark.parametrize("seed", range(40))
def test_people_editing_at_once_end_up_with_the_same_text(seed: int) -> None:
    simulate(seed, importer=False)


@pytest.mark.parametrize("seed", range(100, 220))
def test_imported_ops_with_ids_of_their_own_too(seed: int) -> None:
    simulate(seed, importer=True)
