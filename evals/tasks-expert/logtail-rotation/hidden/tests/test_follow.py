"""The follower against the README: random runs of writes, rotations, truncations and polls
compared poll by poll with a reference, then the rules one at a time."""

import random
import tracemalloc

import model
import pytest

from logtail import FakeFS, Follower
from logtail.rotate import copytruncate, rotate

LOG = "app.log"


class CheckedFS(FakeFS):
    """A FakeFS whose handles refuse reads bigger than `limit` characters."""

    limit = 1 << 30

    def open(self, path: str):
        handle = super().open(path)
        plain = handle.read

        def read(offset: int, size: int) -> str:
            assert size <= self.limit, f"read of {size} characters; chunk_size is {self.limit}"
            return plain(offset, size)

        handle.read = read
        return handle


class Run:
    """A program logging to app.log, logrotate, and both file systems kept in step."""

    def __init__(self, rng: random.Random, max_line: int) -> None:
        self.rng = rng
        self.max_line = max_line
        self.fs = CheckedFS()
        self.files = model.Files()
        self.writer = None
        self.serial = 0
        self.history: list[str] = []
        if rng.random() < 0.85:
            self.reopen()
            for _ in range(rng.randint(0, 3)):
                self.write()

    def reopen(self) -> None:
        self.writer = (self.fs.writer(LOG), self.files.open_for_append(LOG))
        self.history.append("reopen")

    def text(self) -> str:
        rng = self.rng
        parts = []
        for _ in range(rng.randint(0, 3)):
            self.serial += 1
            filler = "x" * rng.choice([0, 0, 1, 2, self.max_line - 4, self.max_line,
                                       2 * self.max_line + 1])
            parts.append(f"e{self.serial}{filler}\n")
        if rng.random() < 0.15:
            parts.append("\n")
        if rng.random() < 0.4:
            self.serial += 1
            parts.append(f"p{self.serial}" + "y" * rng.choice([0, 1, self.max_line]))
        return "".join(parts)

    def write(self) -> None:
        if self.writer is None:
            self.reopen()
        text = self.text()
        self.writer[0].write(text)
        self.files.write(self.writer[1], text)
        self.history.append(f"write {text!r}")

    def step(self) -> None:
        before = len(self.history)
        self.change()
        if len(self.history) == before:
            self.history.append("nothing")

    def change(self) -> None:
        rng = self.rng
        roll = rng.random()
        exists = self.fs.exists(LOG)
        if roll < 0.45:
            self.write()
        elif roll < 0.55:
            if self.fs.exists(LOG + ".1"):
                self.fs.unlink(LOG + ".1")
                self.files.unlink(LOG + ".1")
            if exists:
                create = rng.random() < 0.6
                rotate(self.fs, LOG, keep=1, create=create)
                self.files.rename(LOG, LOG + ".1")
                if create:
                    self.files.create(LOG)
                self.history.append(f"rotate create={create}")
        elif roll < 0.62:
            self.reopen()
        elif roll < 0.68 and exists:
            copytruncate(self.fs, LOG, keep=1)
            self.files.copy(LOG, LOG + ".1")
            self.files.truncate(LOG, 0)
            self.history.append("copytruncate")
        elif roll < 0.71 and exists:
            self.fs.unlink(LOG)
            self.files.unlink(LOG)
            self.history.append("unlink")
        elif roll < 0.73 and exists:
            size = rng.randint(0, self.fs.stat(LOG).size)
            self.fs.truncate(LOG, size)
            self.files.truncate(LOG, size)
            self.history.append(f"truncate to {size}")
        elif roll < 0.76 and self.fs.exists(LOG + ".1"):
            self.fs.rename(LOG + ".1", LOG)
            self.files.rename(LOG + ".1", LOG)
            self.history.append("moved app.log.1 back")
        elif roll < 0.8:
            self.serial += 1
            text = f"a{self.serial}\n"
            self.fs.append(LOG, text)
            self.files.write(self.files.open_for_append(LOG), text)
            self.history.append(f"append {text!r}")
        else:
            self.history.append("poll")


@pytest.mark.parametrize("seed", range(300))
def test_random_runs_deliver_what_the_reference_delivers(seed: int) -> None:
    rng = random.Random(seed)
    max_line = rng.choice([4, 6, 9, 16, 50])
    chunk = rng.choice([1, 2, 5, 8, 64])
    run = Run(rng, max_line)
    run.fs.limit = chunk
    from_end = rng.random() < 0.15
    follower = Follower(run.fs, LOG, max_line=max_line, chunk_size=chunk, from_end=from_end)
    reference = model.Reference(run.files, LOG, max_line, from_end=from_end)
    delivered: list[str] = []
    for number in range(70):
        run.step()
        if run.history[-1] == "poll" or rng.random() < 0.25:
            got, want = follower.poll(), reference.poll()
            delivered += got
            assert got == want, (
                f"seed {seed} (max_line {max_line}, chunk_size {chunk}, from_end {from_end}), "
                f"poll after step {number}: got {got}, want {want}\n"
                f"delivered before: {delivered[-12:-len(got) or None]}\n"
                f"recent history: {run.history[-12:]}"
            )
    assert follower.poll() == reference.poll()
    assert run.fs.chars_read <= reference.chars, "some text was read more than once"


# -- the rules one at a time


def lines_of(follower: Follower) -> list[str]:
    return follower.poll()


def test_lines_written_to_the_old_file_after_a_rename_are_not_lost() -> None:
    fs = FakeFS()
    app = fs.writer(LOG)
    app.write("one\ntwo\n")
    follower = Follower(fs, LOG)
    assert follower.poll() == ["one", "two"]

    app.write("three\n")
    rotate(fs, LOG)  # app.log -> app.log.1, new empty app.log
    app.write("four\n")  # the program hasn't reopened its log yet
    fs.append(LOG, "five\n")

    assert follower.poll() == ["three", "four", "five"]
    app.write("lost\n")  # written to app.log.1 after the follower moved on
    fs.append(LOG, "six\n")
    assert follower.poll() == ["six"]


def test_the_old_file_is_kept_while_the_path_is_missing() -> None:
    fs = FakeFS()
    app = fs.writer(LOG)
    follower = Follower(fs, LOG)
    app.write("a\n")
    rotate(fs, LOG, create=False)
    app.write("b\n")
    assert follower.poll() == ["a", "b"]
    app.write("c\npart")
    assert follower.poll() == ["c"]

    app = fs.writer(LOG)  # the program reopens: a new app.log
    app.write("d\n")
    assert follower.poll() == ["part", "d"]


def test_a_deleted_and_recreated_file_is_read_from_the_start() -> None:
    fs = FakeFS()
    fs.append(LOG, "a\nb")
    follower = Follower(fs, LOG)
    assert follower.poll() == ["a"]
    fs.unlink(LOG)
    assert follower.poll() == []
    fs.append(LOG, "c\n")
    assert follower.poll() == ["b", "c"]


def test_a_partial_line_waits_for_its_newline() -> None:
    fs = FakeFS()
    follower = Follower(fs, LOG)
    fs.append(LOG, "hel")
    assert follower.poll() == []
    fs.append(LOG, "lo")
    assert follower.poll() == []
    fs.append(LOG, " world\nnext")
    assert follower.poll() == ["hello world"]
    fs.append(LOG, "\n\n")
    assert follower.poll() == ["next", ""]


def test_a_partial_line_is_delivered_alone_when_its_file_is_rotated_away() -> None:
    fs = FakeFS()
    app = fs.writer(LOG)
    follower = Follower(fs, LOG)
    app.write("done\nhalf a li")
    assert follower.poll() == ["done"]
    rotate(fs, LOG)
    fs.append(LOG, "ne\nfresh\n")

    assert follower.poll() == ["half a li", "ne", "fresh"]


def test_copytruncate() -> None:
    fs = FakeFS()
    app = fs.writer(LOG)
    follower = Follower(fs, LOG)
    app.write("1\n2\n3\nunfinished")
    assert follower.poll() == ["1", "2", "3"]

    copytruncate(fs, LOG)
    app.write("4\n")
    assert follower.poll() == ["unfinished", "4"]
    app.write("5\n")
    assert follower.poll() == ["5"]


def test_a_truncation_the_follower_cant_see() -> None:
    fs = FakeFS()
    follower = Follower(fs, LOG)
    fs.append(LOG, "abc\n")
    assert follower.poll() == ["abc"]
    fs.truncate(LOG, 0)
    fs.append(LOG, "wxyz\n12\n")  # longer than what was read: looks like growth

    assert follower.poll() == ["", "12"]


def test_a_file_seen_by_no_poll_is_skipped() -> None:
    fs = FakeFS()
    follower = Follower(fs, LOG)
    fs.append(LOG, "first\n")
    assert follower.poll() == ["first"]
    rotate(fs, LOG)
    fs.append(LOG, "middle\n")
    rotate(fs, LOG)
    fs.append(LOG, "last\n")

    assert follower.poll() == ["last"]


def test_long_lines_come_in_pieces() -> None:
    fs = FakeFS()
    follower = Follower(fs, LOG, max_line=4)
    fs.append(LOG, "abcdefghij\nabcd\n\nabcdefgh")
    assert follower.poll() == ["abcd", "efgh", "ij", "abcd", "", "abcd"]
    fs.append(LOG, "\n")
    assert follower.poll() == ["efgh"]
    fs.append(LOG, "abcdef")
    assert follower.poll() == ["abcd"]
    fs.append(LOG, "gh")
    assert follower.poll() == []
    fs.append(LOG, "ijk\n")
    assert follower.poll() == ["efgh", "ijk"]


def test_from_end_skips_what_is_there() -> None:
    fs = FakeFS()
    fs.append(LOG, "old\nold")
    follower = Follower(fs, LOG, from_end=True)
    fs.append(LOG, "er\nnew\n")
    assert follower.poll() == ["er", "new"]


def test_a_missing_file_is_waited_for() -> None:
    fs = FakeFS()
    follower = Follower(fs, LOG, from_end=True)
    assert follower.poll() == []
    fs.append(LOG, "hello\n")
    assert follower.poll() == ["hello"]


def test_on_line_receives_the_lines() -> None:
    fs = FakeFS()
    seen: list[str] = []
    follower = Follower(fs, LOG, on_line=seen.append)
    fs.append(LOG, "a\nb\n")
    assert follower.poll() == []
    assert seen == ["a", "b"]


def test_reads_are_chunked_and_never_repeated() -> None:
    fs = CheckedFS()
    fs.limit = 1000
    follower = Follower(fs, LOG, chunk_size=1000)
    fs.append(LOG, "".join(f"line {n}\n" for n in range(5000)))
    assert len(follower.poll()) == 5000
    size = fs.stat(LOG).size
    for n in range(50):
        fs.append(LOG, f"more {n}\n")
        follower.poll()
    assert fs.chars_read == fs.stat(LOG).size
    assert fs.chars_read < size + 50 * 9


@pytest.mark.parametrize("shape", ["short lines", "one long line"])
def test_memory_stays_bounded_whatever_the_file(shape: str) -> None:
    fs = FakeFS()
    if shape == "short lines":
        fs.append(LOG, "a log line of some length\n" * 300_000)
    else:
        fs.append(LOG, "z" * 8_000_000 + "\n")
    count = 0

    def take(line: str) -> None:
        nonlocal count
        count += 1

    follower = Follower(fs, LOG, max_line=4096, chunk_size=16384, on_line=take)
    tracemalloc.start()
    try:
        follower.poll()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count == (300_000 if shape == "short lines" else 8_000_000 // 4096 + 1)
    assert peak < 1_000_000, f"peak {peak} bytes while following a {fs.stat(LOG).size}-char file"
