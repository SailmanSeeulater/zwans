"""Places an audit line can end up."""

import os
import sys


class PlainFileSink:
    def __init__(self, path: str) -> None:
        self.path = path

    def emit(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class RotatingFileSink(PlainFileSink):
    """Like PlainFileSink, but moves a full log aside to `<path>.1` first."""

    def __init__(self, path: str, max_bytes: int) -> None:
        super().__init__(path)
        self.max_bytes = max_bytes

    def emit(self, line: str) -> None:
        self._rotate_if_needed()
        self._write_line(line)

    def _rotate_if_needed(self) -> None:
        if os.path.exists(self.path) and os.path.getsize(self.path) >= self.max_bytes:
            os.replace(self.path, self.path + ".1")

    def _write_line(self, line: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()


class StderrSink:
    def emit(self, line: str) -> None:
        print(line, file=sys.stderr)


class MemorySink:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def emit(self, line: str) -> None:
        self.lines.append(line)


def make_sink(settings: dict):
    kind = settings["audit_sink"]
    if kind == "rotating":
        return RotatingFileSink(settings["audit_path"], settings["audit_max_bytes"])
    if kind == "plain":
        return PlainFileSink(settings["audit_path"])
    if kind == "stderr":
        return StderrSink()
    return MemorySink()
