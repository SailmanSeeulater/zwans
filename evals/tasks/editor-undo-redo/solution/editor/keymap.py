"""What each key does to the buffer."""

from collections.abc import Callable

from editor.buffer import Buffer


def _home(buffer: Buffer) -> None:
    start = buffer.text.rfind("\n", 0, buffer.cursor) + 1
    buffer.move_to(start)


def _end(buffer: Buffer) -> None:
    end = buffer.text.find("\n", buffer.cursor)
    buffer.move_to(len(buffer.text) if end == -1 else end)


def _left(buffer: Buffer) -> None:
    buffer.move_to(max(0, buffer.cursor - 1))


def _right(buffer: Buffer) -> None:
    buffer.move_to(min(len(buffer.text), buffer.cursor + 1))


KEYMAP: dict[str, Callable[[Buffer], object]] = {
    "backspace": lambda buffer: buffer.backspace(),
    "delete": lambda buffer: buffer.delete_forward(),
    "enter": lambda buffer: buffer.insert("\n"),
    "tab": lambda buffer: buffer.insert("    "),
    "home": _home,
    "end": _end,
    "left": _left,
    "right": _right,
    "ctrl+z": lambda buffer: buffer.undo(),
    "ctrl+y": lambda buffer: buffer.redo(),
    "ctrl+shift+z": lambda buffer: buffer.redo(),
}


def handle_key(buffer: Buffer, key: str) -> None:
    """Apply a key press. Keys not in KEYMAP that are a single character are typed."""
    action = KEYMAP.get(key)
    if action is not None:
        action(buffer)
    elif len(key) == 1:
        buffer.insert(key)
    else:
        raise KeyError(f"no binding for {key!r}")
