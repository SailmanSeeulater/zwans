import pytest

from editor.buffer import Buffer
from editor.keymap import handle_key


def test_insert_at_the_cursor() -> None:
    buffer = Buffer("hed")
    buffer.move_to(2)
    buffer.insert("llo worl")

    assert buffer.text == "hello world"
    assert buffer.cursor == 10


def test_backspace_and_delete_forward() -> None:
    buffer = Buffer("abcdef")
    buffer.move_to(3)

    assert buffer.backspace(2) == "bc"
    assert buffer.delete_forward() == "d"
    assert buffer.text == "aef"
    assert buffer.cursor == 1
    assert buffer.backspace(5) == "a"
    assert buffer.cursor == 0


def test_replace_all() -> None:
    buffer = Buffer("one fish two fish")

    assert buffer.replace_all("fish", "cat") == 2
    assert buffer.text == "one cat two cat"
    assert buffer.cursor == len(buffer.text)


def test_move_outside_the_text() -> None:
    with pytest.raises(IndexError):
        Buffer("abc").move_to(4)


def test_line_and_column() -> None:
    buffer = Buffer("first\nsecond")
    buffer.move_to(8)

    assert buffer.line_and_column() == (2, 3)


def test_keys() -> None:
    buffer = Buffer()
    for key in ["h", "i", "enter", "x", "backspace", "home", "tab", "end", "!"]:
        handle_key(buffer, key)

    assert buffer.text == "hi\n    !"

    with pytest.raises(KeyError):
        handle_key(buffer, "ctrl+q")
