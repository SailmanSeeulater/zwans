"""A text buffer with a cursor, and undo/redo."""

from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class _Step:
    before: tuple[str, int]  # text and cursor right before the edit
    after: tuple[str, int]  # and right after it


class Buffer:
    def __init__(self, text: str = "", history_limit: int = 100) -> None:
        self._text = text
        self._cursor = len(text)
        self._undo: deque[_Step] = deque(maxlen=history_limit)
        self._redo: list[_Step] = []
        self._group_depth = 0
        self._group_before: tuple[str, int] | None = None

    @property
    def text(self) -> str:
        return self._text

    @property
    def cursor(self) -> int:
        """Position between characters: 0 is before the first, len(text) after the last."""
        return self._cursor

    # Undo and redo

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _state(self) -> tuple[str, int]:
        return self._text, self._cursor

    def _restore(self, state: tuple[str, int]) -> None:
        self._text, self._cursor = state

    def _record(self, before: tuple[str, int]) -> None:
        if self._group_depth:
            return  # the outermost group records the whole thing when it ends
        if before[0] == self._text:
            return  # nothing changed
        self._undo.append(_Step(before, self._state()))
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        step = self._undo.pop()
        self._restore(step.before)
        self._redo.append(step)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        step = self._redo.pop()
        self._restore(step.after)
        self._undo.append(step)
        return True

    @contextmanager
    def group(self) -> Iterator[None]:
        """Make every edit inside the with-block one undo step."""
        if self._group_depth == 0:
            self._group_before = self._state()
        self._group_depth += 1
        try:
            yield
        finally:
            self._group_depth -= 1
            if self._group_depth == 0:
                before = self._group_before
                self._group_before = None
                assert before is not None
                self._record(before)

    # Editing

    def move_to(self, position: int) -> None:
        if not 0 <= position <= len(self._text):
            raise IndexError(f"cursor position {position} is outside the text")
        self._cursor = position

    def insert(self, text: str) -> None:
        """Insert text at the cursor and move the cursor past it."""
        before_state = self._state()
        before, after = self._text[: self._cursor], self._text[self._cursor :]
        self._text = before + text + after
        self._cursor += len(text)
        self._record(before_state)

    def backspace(self, count: int = 1) -> str:
        """Delete up to count characters before the cursor and return them."""
        before_state = self._state()
        start = max(0, self._cursor - count)
        removed = self._text[start : self._cursor]
        self._text = self._text[:start] + self._text[self._cursor :]
        self._cursor = start
        self._record(before_state)
        return removed

    def delete_forward(self, count: int = 1) -> str:
        """Delete up to count characters after the cursor and return them."""
        before_state = self._state()
        end = min(len(self._text), self._cursor + count)
        removed = self._text[self._cursor : end]
        self._text = self._text[: self._cursor] + self._text[end:]
        self._record(before_state)
        return removed

    def replace_all(self, old: str, new: str) -> int:
        """Replace every occurrence of old with new and return how many there were.

        The cursor stays where it was, or moves to the end if the text got shorter than that.
        """
        if not old:
            raise ValueError("cannot replace an empty string")
        before_state = self._state()
        count = self._text.count(old)
        self._text = self._text.replace(old, new)
        self._cursor = min(self._cursor, len(self._text))
        self._record(before_state)
        return count

    def line_and_column(self) -> tuple[int, int]:
        """The cursor's line and column, both counted from 1, for the status bar."""
        before = self._text[: self._cursor]
        line = before.count("\n") + 1
        column = len(before) - (before.rfind("\n") + 1) + 1
        return line, column
