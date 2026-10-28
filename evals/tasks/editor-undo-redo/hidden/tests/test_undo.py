import pytest

from editor.buffer import Buffer
from editor.keymap import handle_key


def state(buffer: Buffer) -> tuple[str, int]:
    return buffer.text, buffer.cursor


def test_nothing_to_undo_or_redo() -> None:
    buffer = Buffer("abc")

    assert not buffer.can_undo
    assert not buffer.can_redo
    assert buffer.undo() is False
    assert buffer.redo() is False
    assert state(buffer) == ("abc", 3)


def test_undo_and_redo_one_insert() -> None:
    buffer = Buffer("hed")
    buffer.move_to(2)
    buffer.insert("llo worl")

    assert buffer.can_undo
    assert buffer.undo() is True
    assert state(buffer) == ("hed", 2)
    assert buffer.can_redo
    assert not buffer.can_undo
    assert buffer.redo() is True
    assert state(buffer) == ("hello world", 10)
    assert not buffer.can_redo


def test_every_kind_of_edit_is_undone_in_order() -> None:
    buffer = Buffer("one fish two fish")
    befores: list[tuple[str, int]] = []
    afters: list[tuple[str, int]] = []

    def edit(action: object) -> None:
        befores.append(state(buffer))
        action()  # type: ignore[operator]
        afters.append(state(buffer))

    buffer.move_to(3)
    edit(lambda: buffer.backspace(2))
    edit(lambda: buffer.delete_forward(5))
    buffer.move_to(4)
    edit(lambda: buffer.replace_all("fish", "cats"))
    buffer.move_to(0)
    edit(lambda: buffer.insert(">> "))
    buffer.move_to(2)

    for expected in reversed(befores):
        assert buffer.undo() is True
        assert state(buffer) == expected
    assert buffer.undo() is False
    assert buffer.text == "one fish two fish"

    for expected in afters:
        assert buffer.redo() is True
        assert state(buffer) == expected
    assert buffer.redo() is False


def test_undo_restores_the_cursor_from_before_the_edit() -> None:
    buffer = Buffer("abc")
    buffer.insert("def")
    buffer.move_to(1)

    buffer.undo()

    assert state(buffer) == ("abc", 3)


def test_moves_are_not_undo_steps() -> None:
    buffer = Buffer("abc")
    buffer.move_to(0)
    buffer.move_to(2)

    assert not buffer.can_undo


def test_moving_keeps_redo() -> None:
    buffer = Buffer("abc")
    buffer.insert("d")
    buffer.undo()
    buffer.move_to(0)

    assert buffer.redo() is True
    assert state(buffer) == ("abcd", 4)


def test_a_new_edit_clears_redo() -> None:
    buffer = Buffer()
    buffer.insert("a")
    buffer.insert("b")
    buffer.undo()

    buffer.insert("c")

    assert not buffer.can_redo
    assert buffer.redo() is False
    assert buffer.text == "ac"
    buffer.undo()
    assert buffer.text == "a"


@pytest.mark.parametrize(
    "no_op",
    [
        lambda b: b.insert(""),
        lambda b: (b.move_to(0), b.backspace()),
        lambda b: (b.move_to(len(b.text)), b.delete_forward()),
        lambda b: b.replace_all("zzz", "y"),
        lambda b: b.replace_all("b", "b"),
        lambda b: b.backspace(0),
    ],
)
def test_no_op_edits_are_not_recorded(no_op: object) -> None:
    buffer = Buffer("abc")
    buffer.insert("d")
    buffer.insert("e")
    buffer.undo()

    no_op(buffer)  # type: ignore[operator]

    assert buffer.can_redo
    buffer.undo()
    assert buffer.text == "abc"
    assert not buffer.can_undo


def test_group_is_one_step() -> None:
    buffer = Buffer("x")
    buffer.insert("1")

    with buffer.group():
        buffer.insert("2")
        buffer.move_to(0)
        buffer.insert("3")
        buffer.replace_all("x", "y")

    assert state(buffer) == ("3y12", 1)
    buffer.undo()
    assert state(buffer) == ("x1", 2)
    buffer.redo()
    assert state(buffer) == ("3y12", 1)
    buffer.undo()
    buffer.undo()
    assert state(buffer) == ("x", 1)


def test_nested_groups_make_one_step() -> None:
    buffer = Buffer()
    with buffer.group():
        buffer.insert("a")
        with buffer.group():
            buffer.insert("b")
            buffer.insert("c")
        buffer.insert("d")

    assert buffer.undo() is True
    assert state(buffer) == ("", 0)
    assert not buffer.can_undo


def test_an_empty_group_records_nothing() -> None:
    buffer = Buffer("abc")
    buffer.insert("d")
    buffer.undo()

    with buffer.group():
        buffer.move_to(0)
        buffer.insert("")

    assert not buffer.can_undo
    assert buffer.can_redo


def test_a_group_after_undo_clears_redo() -> None:
    buffer = Buffer()
    buffer.insert("a")
    buffer.undo()

    with buffer.group():
        buffer.insert("b")

    assert not buffer.can_redo


def test_history_limit() -> None:
    buffer = Buffer(history_limit=3)
    for letter in "abcde":
        buffer.insert(letter)

    undone = 0
    while buffer.undo():
        undone += 1

    assert undone == 3
    assert buffer.text == "ab"
    for _ in range(3):
        assert buffer.redo()
    assert buffer.text == "abcde"


def test_default_history_limit_is_100() -> None:
    buffer = Buffer()
    for _ in range(150):
        buffer.insert("x")

    undone = 0
    while buffer.undo():
        undone += 1

    assert undone == 100
    assert buffer.text == "x" * 50


def test_keys() -> None:
    buffer = Buffer()
    for key in ["a", "b", "c", "ctrl+z", "ctrl+z"]:
        handle_key(buffer, key)
    assert state(buffer) == ("a", 1)

    handle_key(buffer, "ctrl+y")
    assert buffer.text == "ab"
    handle_key(buffer, "ctrl+shift+z")
    assert buffer.text == "abc"
    handle_key(buffer, "ctrl+y")
    assert buffer.text == "abc"
