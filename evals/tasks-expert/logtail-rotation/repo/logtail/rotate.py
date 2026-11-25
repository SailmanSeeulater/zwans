"""What logrotate does to a log, on a FakeFS: for trying followers out."""

from logtail.fakefs import FakeFS


def shift(fs: FakeFS, path: str, keep: int) -> None:
    """Move path.N to path.N+1 for each kept generation (dropping the oldest)."""
    oldest = f"{path}.{keep}"
    if fs.exists(oldest):
        fs.unlink(oldest)
    for number in range(keep - 1, 0, -1):
        if fs.exists(f"{path}.{number}"):
            fs.rename(f"{path}.{number}", f"{path}.{number + 1}")


def rotate(fs: FakeFS, path: str, keep: int = 3, create: bool = True) -> None:
    """The default: rename the log to path.1 and (with `create`) start a new, empty one.

    A program that still has the old file open keeps writing to path.1 until it reopens
    its log.
    """
    shift(fs, path, keep)
    fs.rename(path, f"{path}.1")
    if create:
        fs.create(path)


def copytruncate(fs: FakeFS, path: str, keep: int = 3) -> None:
    """For programs that can't reopen their log: copy it to path.1, then empty it."""
    shift(fs, path, keep)
    fs.copy(path, f"{path}.1")
    fs.truncate(path, 0)
