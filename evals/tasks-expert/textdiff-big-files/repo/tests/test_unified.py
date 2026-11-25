import random

import pytest

from linediff import PatchError, apply, parse, unified
from linediff.cli import main


def test_the_readme_hunk() -> None:
    assert unified(["a", "b", "c"], ["a", "c", "e"]) == (
        "--- old\n+++ new\n@@ -1,3 +1,3 @@\n a\n-b\n c\n+e\n"
    )


def test_identical_files_give_nothing() -> None:
    assert unified(["a", "b"], ["a", "b"]) == ""


def test_changes_far_apart_get_their_own_hunks() -> None:
    old = [str(i) for i in range(1, 21)]
    new = list(old)
    new[1] = "two"
    new[17] = "eighteen"

    text = unified(old, new, context=2, old_name="a.txt", new_name="b.txt")

    assert text == (
        "--- a.txt\n+++ b.txt\n"
        "@@ -1,4 +1,4 @@\n 1\n-2\n+two\n 3\n 4\n"
        "@@ -16,5 +16,5 @@\n 16\n 17\n-18\n+eighteen\n 19\n 20\n"
    )


def test_an_insertion_at_the_top_with_no_context() -> None:
    assert unified(["b"], ["a", "b"], context=0) == "--- old\n+++ new\n@@ -0,0 +1,1 @@\n+a\n"


def test_headers_without_counts_are_read() -> None:
    hunks = parse("@@ -2 +2 @@\n-b\n+B\n")

    assert (hunks[0].old_start, hunks[0].old_len, hunks[0].new_len) == (2, 1, 1)
    assert apply("@@ -2 +2 @@\n-b\n+B\n", ["a", "b", "c"]) == ["a", "B", "c"]


def test_a_patch_that_doesnt_fit_is_refused() -> None:
    patch = unified(["a", "b", "c"], ["a", "x", "c"])

    with pytest.raises(PatchError):
        apply(patch, ["a", "y", "c"])


@pytest.mark.parametrize("seed", range(30))
def test_applying_a_diff_gives_the_new_file(seed: int) -> None:
    rng = random.Random(seed)
    old = [rng.choice(["a", "b", "c", ""]) for _ in range(rng.randint(0, 25))]
    new = [rng.choice(["a", "b", "c", ""]) for _ in range(rng.randint(0, 25))]

    for context in (0, 1, 3):
        assert apply(unified(old, new, context), old) == new


def test_the_command_line(tmp_path, capsys) -> None:
    (tmp_path / "old.txt").write_text("one\ntwo\nthree\n")
    (tmp_path / "new.txt").write_text("one\n2\nthree\n")
    old, new = str(tmp_path / "old.txt"), str(tmp_path / "new.txt")

    assert main([old, new, "-U", "1"]) == 1
    patch = capsys.readouterr().out
    assert patch == f"--- {old}\n+++ {new}\n@@ -1,3 +1,3 @@\n one\n-two\n+2\n three\n"

    (tmp_path / "fix.diff").write_text(patch)
    assert main(["--apply", str(tmp_path / "fix.diff"), old]) == 0
    assert capsys.readouterr().out == "one\n2\nthree\n"

    assert main([old, old]) == 0
    assert capsys.readouterr().out == ""
