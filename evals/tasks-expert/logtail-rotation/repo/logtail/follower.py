"""Following one log file by name."""

from typing import Callable


class Follower:
    """Delivers the lines written to the file at `path`.

    Call poll() whenever you like; it returns the lines completed since the last call, or
    hands them to `on_line` if one was given (and then returns an empty list).
    """

    def __init__(
        self,
        fs,
        path: str,
        *,
        from_end: bool = False,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.fs = fs
        self.path = path
        self.on_line = on_line
        self._position = 0
        self._partial = ""
        if from_end:
            try:
                self._position = fs.stat(path).size
            except FileNotFoundError:
                pass

    def poll(self) -> list[str]:
        lines: list[str] = []
        emit = lines.append if self.on_line is None else self.on_line
        try:
            size = self.fs.stat(self.path).size
        except FileNotFoundError:
            return lines
        if size < self._position:
            self._position = 0  # truncated
        if size == self._position:
            return lines
        handle = self.fs.open(self.path)
        try:
            data = handle.read(self._position, size - self._position)
        finally:
            handle.close()
        self._position += len(data)
        pieces = (self._partial + data).split("\n")
        self._partial = pieces.pop()
        for line in pieces:
            emit(line)
        return lines

    def close(self) -> None:
        pass
