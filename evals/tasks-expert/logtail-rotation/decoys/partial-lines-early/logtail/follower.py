"""Following one log file by name, through rotation and truncation."""

from typing import Callable

DEFAULT_MAX_LINE = 64 * 1024
DEFAULT_CHUNK = 64 * 1024


class Follower:
    """Delivers the lines written to the file at `path`, as `tail -F` shows them.

    Call poll() whenever you like; it returns the lines completed since the last call, or
    hands them to `on_line` if one was given (and then returns an empty list).
    """

    def __init__(
        self,
        fs,
        path: str,
        *,
        max_line: int = DEFAULT_MAX_LINE,
        chunk_size: int = DEFAULT_CHUNK,
        from_end: bool = False,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        if max_line < 1 or chunk_size < 1:
            raise ValueError("max_line and chunk_size must be positive")
        self.fs = fs
        self.path = path
        self.max_line = max_line
        self.chunk_size = chunk_size
        self.on_line = on_line
        self.rotations = 0
        self.truncations = 0
        self._handle = None
        self._position = 0
        self._held = ""
        self._open(at_end=from_end)

    def _open(self, at_end: bool) -> None:
        try:
            handle = self.fs.open(self.path)
        except FileNotFoundError:
            return
        self._handle = handle
        self._position = handle.size() if at_end else 0
        self._held = ""

    def poll(self) -> list[str]:
        lines: list[str] = []
        emit = lines.append if self.on_line is None else self.on_line
        if self._handle is None:
            self._open(at_end=False)
            if self._handle is None:
                return lines
        elif self._replaced():
            self._drain(emit)
            self._flush(emit)
            self._handle.close()
            self._handle = None
            self.rotations += 1
            self._open(at_end=False)
            if self._handle is None:
                return lines
        self._drain(emit)
        return lines

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    # -- the steps

    def _replaced(self) -> bool:
        """Whether the path now names a different file from the one being read."""
        try:
            current = self.fs.stat(self.path)
        except FileNotFoundError:
            return False  # gone for now; writers may still be appending to our file
        return current.inode != self._handle.inode

    def _drain(self, emit: Callable[[str], None]) -> None:
        """Read the followed file from where we were to its end, a chunk at a time."""
        size = self._handle.size()
        if size < self._position:
            self.truncations += 1
            self._flush(emit)
            self._position = 0
        while self._position < size:
            chunk = self._handle.read(self._position, min(self.chunk_size, size - self._position))
            if not chunk:
                break
            self._position += len(chunk)
            self._feed(chunk, emit)

    def _feed(self, chunk: str, emit: Callable[[str], None]) -> None:
        start = 0
        while True:
            end = chunk.find("\n", start)
            if end == -1:
                break
            self._take(chunk[start:end], emit, complete=True)
            start = end + 1
        if start < len(chunk):
            self._take(chunk[start:], emit, complete=True)

    def _take(self, text: str, emit: Callable[[str], None], complete: bool) -> None:
        held = self._held + text
        while len(held) > self.max_line:
            emit(held[: self.max_line])
            held = held[self.max_line :]
        if complete:
            emit(held)
            held = ""
        self._held = held

    def _flush(self, emit: Callable[[str], None]) -> None:
        """Deliver held text that will never be finished in the stretch it came from."""
        if self._held:
            emit(self._held)
            self._held = ""
