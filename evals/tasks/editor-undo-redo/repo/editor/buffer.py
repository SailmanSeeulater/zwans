"""A text buffer with a cursor."""


class Buffer:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self._cursor = len(text)

    @property
    def text(self) -> str:
        return self._text

    @property
    def cursor(self) -> int:
        """Position between characters: 0 is before the first, len(text) after the last."""
        return self._cursor

    def move_to(self, position: int) -> None:
        if not 0 <= position <= len(self._text):
            raise IndexError(f"cursor position {position} is outside the text")
        self._cursor = position

    def insert(self, text: str) -> None:
        """Insert text at the cursor and move the cursor past it."""
        before, after = self._text[: self._cursor], self._text[self._cursor :]
        self._text = before + text + after
        self._cursor += len(text)

    def backspace(self, count: int = 1) -> str:
        """Delete up to count characters before the cursor and return them."""
        start = max(0, self._cursor - count)
        removed = self._text[start : self._cursor]
        self._text = self._text[:start] + self._text[self._cursor :]
        self._cursor = start
        return removed

    def delete_forward(self, count: int = 1) -> str:
        """Delete up to count characters after the cursor and return them."""
        end = min(len(self._text), self._cursor + count)
        removed = self._text[self._cursor : end]
        self._text = self._text[: self._cursor] + self._text[end:]
        return removed

    def replace_all(self, old: str, new: str) -> int:
        """Replace every occurrence of old with new and return how many there were.

        The cursor stays where it was, or moves to the end if the text got shorter than that.
        """
        if not old:
            raise ValueError("cannot replace an empty string")
        count = self._text.count(old)
        self._text = self._text.replace(old, new)
        self._cursor = min(self._cursor, len(self._text))
        return count

    def line_and_column(self) -> tuple[int, int]:
        """The cursor's line and column, both counted from 1, for the status bar."""
        before = self._text[: self._cursor]
        line = before.count("\n") + 1
        column = len(before) - (before.rfind("\n") + 1) + 1
        return line, column
