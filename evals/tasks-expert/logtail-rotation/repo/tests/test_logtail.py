import io

from logtail import FakeFS, Follower, Tail
from logtail.rotate import copytruncate, rotate
from logtail.tail import main


def test_lines_are_delivered_once_in_order() -> None:
    fs = FakeFS()
    app = fs.writer("app.log")
    follower = Follower(fs, "app.log")

    app.write("one\ntwo\n")
    assert follower.poll() == ["one", "two"]
    assert follower.poll() == []
    app.write("three\n")
    assert follower.poll() == ["three"]


def test_an_unfinished_line_waits() -> None:
    fs = FakeFS()
    follower = Follower(fs, "app.log")
    fs.append("app.log", "par")
    assert follower.poll() == []
    fs.append("app.log", "tial\n")
    assert follower.poll() == ["partial"]


def test_existing_text_and_from_end() -> None:
    fs = FakeFS()
    fs.append("app.log", "before\n")

    assert Follower(fs, "app.log").poll() == ["before"]
    skipping = Follower(fs, "app.log", from_end=True)
    fs.append("app.log", "after\n")
    assert skipping.poll() == ["after"]


def test_waits_for_the_file_to_appear() -> None:
    fs = FakeFS()
    follower = Follower(fs, "app.log")
    assert follower.poll() == []
    fs.append("app.log", "here\n")
    assert follower.poll() == ["here"]


def test_truncation_starts_over() -> None:
    fs = FakeFS()
    follower = Follower(fs, "app.log")
    fs.append("app.log", "a long first line\n")
    assert follower.poll() == ["a long first line"]

    fs.truncate("app.log")
    fs.append("app.log", "short\n")
    assert follower.poll() == ["short"]


def test_on_line() -> None:
    fs = FakeFS()
    seen = []
    follower = Follower(fs, "app.log", on_line=seen.append)
    fs.append("app.log", "x\ny\n")

    assert follower.poll() == []
    assert seen == ["x", "y"]


def test_the_fake_file_system_keeps_inodes() -> None:
    fs = FakeFS()
    app = fs.writer("app.log")
    app.write("a\n")
    rotate(fs, "app.log")
    app.write("b\n")

    assert fs.read_text("app.log.1") == "a\nb\n"
    assert fs.read_text("app.log") == ""
    assert fs.stat("app.log.1").inode == app.inode != fs.stat("app.log").inode

    copytruncate(fs, "app.log.1")
    assert fs.read_text("app.log.1.1") == "a\nb\n"
    assert fs.read_text("app.log.1") == ""


def test_tail_follows_several_files() -> None:
    fs = FakeFS()
    tail = Tail(fs, ["a.log", "b.log"])
    fs.append("a.log", "from a\n")
    fs.append("b.log", "from b\n")

    assert tail.poll() == [("a.log", "from a"), ("b.log", "from b")]


def test_command_line(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text("hello\nworld\n")
    out = io.StringIO()

    assert main([str(log), "--polls", "1"], out=out) == 0
    assert out.getvalue() == "hello\nworld\n"


def test_command_line_grep_and_json(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text("GET /a\nPOST /b\nGET /c\n")
    out = io.StringIO()

    assert main([str(log), "--polls", "1", "--grep", "^GET", "--json"], out=out) == 0
    assert [line.split('"line": ')[1] for line in out.getvalue().splitlines()] == [
        '"GET /a"}',
        '"GET /c"}',
    ]
