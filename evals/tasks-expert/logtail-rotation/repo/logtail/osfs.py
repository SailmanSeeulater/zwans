"""The real file system, with the same reading interface as FakeFS."""

import os

from logtail.fakefs import Stat


class OSHandle:
    def __init__(self, path: str) -> None:
        self._file = open(path, encoding="utf-8", errors="replace", newline="")
        self._inode = os.fstat(self._file.fileno()).st_ino
        self._offset = 0

    @property
    def inode(self) -> int:
        return self._inode

    def size(self) -> int:
        return os.fstat(self._file.fileno()).st_size

    def stat(self) -> Stat:
        return Stat(self._inode, self.size())

    def read(self, offset: int, size: int) -> str:
        # Offsets are characters for FakeFS; for real files we read sequentially, which is
        # all a follower does, and keep our own count.
        if offset != self._offset:
            self._file.seek(0)
            self._file.read(offset)
        text = self._file.read(size)
        self._offset = offset + len(text)
        return text

    def close(self) -> None:
        self._file.close()


class OSFS:
    def stat(self, path: str) -> Stat:
        info = os.stat(path)
        return Stat(info.st_ino, info.st_size)

    def open(self, path: str) -> OSHandle:
        return OSHandle(path)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)
