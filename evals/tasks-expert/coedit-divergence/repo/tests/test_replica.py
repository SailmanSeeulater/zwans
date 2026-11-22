from coedit import Insert, Replica


def test_typing_and_sending() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    for index, char in enumerate("hello"):
        bob.apply(ann.insert(index, char))

    assert ann.text() == "hello"
    assert bob.text() == "hello"


def test_typing_in_the_middle() -> None:
    ann = Replica("ann")
    for index, char in enumerate("hllo"):
        ann.insert(index, char)
    ann.insert(1, "e")

    assert ann.text() == "hello"


def test_deleting() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    ops = [ann.insert(index, char) for index, char in enumerate("cart")]
    ops.append(ann.delete(3))
    for op in ops:
        bob.apply(op)

    assert ann.text() == "car"
    assert bob.text() == "car"


def test_two_people_typing_at_the_same_place_end_up_with_the_same_text() -> None:
    ann, bob = Replica("ann"), Replica("bob")
    first = ann.insert(0, "a")
    bob.apply(first)
    from_ann = ann.insert(1, "x")
    from_bob_1 = bob.insert(1, "y")
    from_bob_2 = bob.insert(2, "z")

    ann.apply(from_bob_1)
    ann.apply(from_bob_2)
    bob.apply(from_ann)

    assert ann.text() == bob.text()


def test_the_newer_of_two_characters_typed_at_the_start_comes_first() -> None:
    replica = Replica("ann")
    replica.apply(Insert(id=(1, "bob"), after=None, char="b"))
    replica.apply(Insert(id=(2, "cy"), after=None, char="c"))

    assert replica.text() == "cb"
