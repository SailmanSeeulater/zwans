"""The file systems a build reads and writes.

Builds only touch files through one of these, so the same project can run against the
real disk (DiskFS) or against MemoryFS, which keeps text files in a dict and stamps each
write with the next tick of a counter instead of the wall clock.
"""

import os
from pathlib import Path


class FileSystem:
    """What the builder needs from a file system. Paths use forward slashes."""

    def read(self, path: str) -> str:
        """The file's text; FileNotFoundError if there is none."""
        raise NotImplementedError

    def write(self, path: str, text: str) -> None:
        raise NotImplementedError

    def exists(self, path: str) -> bool:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        """Remove the file; FileNotFoundError if there is none."""
        raise NotImplementedError

    def mtime(self, path: str) -> float:
        """When the file was last modified; FileNotFoundError if there is none."""
        raise NotImplementedError

    def now(self) -> float:
        """The current time on this file system's clock."""
        raise NotImplementedError

    def files(self, prefix: str = "") -> list[str]:
        """Every file whose path starts with `prefix`, sorted."""
        raise NotImplementedError


class MemoryFS(FileSystem):
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self._files: dict[str, str] = {}
        self._mtimes: dict[str, int] = {}
        self._clock = 0
        for path, text in (files or {}).items():
            self.write(path, text)

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    def read(self, path: str) -> str:
        try:
            return self._files[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def write(self, path: str, text: str, mtime: int | None = None) -> None:
        """Write `text`; `mtime` sets the modification time (as `cp -p` or `tar x` would)."""
        if not isinstance(text, str):
            raise TypeError(f"files hold text, not {type(text).__name__}")
        self._files[path] = text
        self._mtimes[path] = self._tick() if mtime is None else mtime

    def touch(self, path: str) -> None:
        """Bump the modification time, creating an empty file if there is none."""
        if path not in self._files:
            self._files[path] = ""
        self._mtimes[path] = self._tick()

    def exists(self, path: str) -> bool:
        return path in self._files

    def delete(self, path: str) -> None:
        if path not in self._files:
            raise FileNotFoundError(path)
        del self._files[path]
        del self._mtimes[path]
        self._tick()

    def mtime(self, path: str) -> int:
        try:
            return self._mtimes[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    def now(self) -> int:
        return self._clock

    def files(self, prefix: str = "") -> list[str]:
        return sorted(path for path in self._files if path.startswith(prefix))

    def snapshot(self) -> dict[str, str]:
        """Every file's text, keyed by path."""
        return dict(self._files)


class DiskFS(FileSystem):
    """Files under a root directory on disk."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, path: str) -> Path:
        return self.root / path

    def read(self, path: str) -> str:
        return self._path(path).read_text(encoding="utf-8")

    def write(self, path: str, text: str) -> None:
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)

    def exists(self, path: str) -> bool:
        return self._path(path).is_file()

    def delete(self, path: str) -> None:
        self._path(path).unlink()

    def mtime(self, path: str) -> float:
        return self._path(path).stat().st_mtime

    def now(self) -> float:
        import time

        return time.time()

    def files(self, prefix: str = "") -> list[str]:
        found = []
        for file in self.root.rglob("*"):
            if file.is_file():
                relative = file.relative_to(self.root).as_posix()
                if relative.startswith(prefix):
                    found.append(relative)
        return sorted(found)
