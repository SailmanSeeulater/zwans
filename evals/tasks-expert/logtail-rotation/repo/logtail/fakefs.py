"""An in-memory file system with the parts of POSIX semantics log rotation depends on.

Files are inodes; a path is just a name for one. Renaming a file moves the name and keeps
the inode, so anyone who has the file open (a writer appending to it, a reader following
it) keeps working on the same file under its new name, or after it has been deleted.
Creating a file at a path that exists gives the path a new, empty inode.

Text is str; offsets and sizes count characters.
"""

from dataclasses import dataclass


@dataclass
class Stat:
    inode: int
    size: int


class _Inode:
    __slots__ = ("number", "data")

    def __init__(self, number: int) -> None:
        self.number = number
        self.data = ""


class Handle:
    """An open file, for reading. It stays on its inode whatever happens to the path."""

    def __init__(self, fs: "FakeFS", inode: _Inode) -> None:
        self._fs = fs
        self._inode = inode
        self.closed = False

    @property
    def inode(self) -> int:
        return self._inode.number

    def size(self) -> int:
        return len(self._inode.data)

    def stat(self) -> Stat:
        return Stat(self._inode.number, len(self._inode.data))

    def read(self, offset: int, size: int) -> str:
        """Up to `size` characters starting at `offset` (fewer at the end of the file)."""
        if self.closed:
            raise ValueError("read from a closed handle")
        if offset < 0 or size < 0:
            raise ValueError("negative offset or size")
        text = self._inode.data[offset : offset + size]
        self._fs.chars_read += len(text)
        self._fs.reads += 1
        return text

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._fs.open_handles -= 1


class Writer:
    """An open file, for appending (O_APPEND): what a program logging to a file holds."""

    def __init__(self, inode: _Inode) -> None:
        self._inode = inode

    @property
    def inode(self) -> int:
        return self._inode.number

    def write(self, text: str) -> None:
        self._inode.data += text


class FakeFS:
    def __init__(self) -> None:
        self._paths: dict[str, _Inode] = {}
        self._next_inode = 100
        self.chars_read = 0  # characters returned by Handle.read, in total
        self.reads = 0  # calls to Handle.read
        self.open_handles = 0

    def _new_inode(self) -> _Inode:
        self._next_inode += 1
        return _Inode(self._next_inode)

    def _get(self, path: str) -> _Inode:
        try:
            return self._paths[path]
        except KeyError:
            raise FileNotFoundError(path) from None

    # -- what writers and logrotate do

    def create(self, path: str) -> None:
        """A new, empty file at `path` (any file already there loses that name)."""
        self._paths[path] = self._new_inode()

    def append(self, path: str, text: str) -> None:
        """Open `path` for appending (creating it if needed), write, close."""
        inode = self._paths.get(path)
        if inode is None:
            inode = self._paths[path] = self._new_inode()
        inode.data += text

    def writer(self, path: str) -> Writer:
        """Open `path` for appending, creating it if needed, and keep it open."""
        inode = self._paths.get(path)
        if inode is None:
            inode = self._paths[path] = self._new_inode()
        return Writer(inode)

    def rename(self, source: str, target: str) -> None:
        """Move the name; a file already at `target` loses its name."""
        self._paths[target] = self._get(source)
        del self._paths[source]

    def unlink(self, path: str) -> None:
        self._get(path)
        del self._paths[path]

    def truncate(self, path: str, size: int = 0) -> None:
        inode = self._get(path)
        inode.data = inode.data[:size]

    def copy(self, source: str, target: str) -> None:
        """A new file at `target` with the same text (as `cp`, not `mv`)."""
        text = self._get(source).data
        inode = self._new_inode()
        inode.data = text
        self._paths[target] = inode

    # -- what readers do

    def exists(self, path: str) -> bool:
        return path in self._paths

    def stat(self, path: str) -> Stat:
        inode = self._get(path)
        return Stat(inode.number, len(inode.data))

    def open(self, path: str) -> Handle:
        handle = Handle(self, self._get(path))
        self.open_handles += 1
        return handle

    def read_text(self, path: str) -> str:
        """The whole file, for tests and debugging (not counted in chars_read)."""
        return self._get(path).data
