import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Mode, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.multi_edit import MultiEditInput, MultiEditTool


def swap(path: str, old: str, new: str, **more: Any) -> dict[str, Any]:
    return {"path": path, "old_string": old, "new_string": new, **more}


def run(ctx: ToolContext, *edits: dict[str, Any]) -> ToolOutput:
    args = MultiEditInput.model_validate({"edits": list(edits)})
    return asyncio.run(MultiEditTool().run(args, ctx))


def permissions(
    tmp_path: Path, mode: Mode, *, allow: Sequence[str] = (), deny: Sequence[str] = ()
) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(mode=mode, allow=list(allow), deny=list(deny)), "test")
    executor = LocalExecutor(tmp_path)

    def inside(path: str) -> bool:
        try:
            executor.relative(path)
        except OSError:
            return False
        return True

    return Permissions(policy, inside, executor.relative, root=executor.root)


def test_several_edits_across_files_are_one_call(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("name = 'old'\n", encoding="utf-8")

    output = run(
        ctx,
        swap("a.py", "x = 1", "x = 10"),
        swap("b.py", "'old'", "'new'"),
        swap("./a.py", "y = 2", "y = x * 2"),  # the same file, spelled another way
    )

    assert (tmp_path / "a.py").read_text("utf-8") == "x = 10\ny = x * 2\n"
    assert (tmp_path / "b.py").read_text("utf-8") == "name = 'new'\n"
    assert output.content == "Replaced 3 places in 2 files: a.py (2), b.py (1)."
    assert output.diff is not None
    assert [line for line in output.diff.splitlines() if line.startswith("+++")] == [
        "+++ b/a.py",
        "+++ b/b.py",
    ]


def test_a_later_edit_sees_what_the_earlier_ones_left(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "v.py").write_text("v = 1\n", encoding="utf-8")

    output = run(ctx, swap("v.py", "v = 1", "v = 2"), swap("v.py", "v = 2", "v = 3"))

    assert (tmp_path / "v.py").read_text("utf-8") == "v = 3\n"
    assert output.content == "Replaced 2 places in 1 file: v.py (2)."


def test_one_edit_that_doesnt_fit_changes_nothing(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")

    with pytest.raises(ToolError, match="Edit 2 of 2 doesn't fit, so nothing was changed") as e:
        run(ctx, swap("a.py", "x = 1", "x = 10"), swap("b.py", "z = 3", "z = 30"))

    assert "old_string was not found in b.py" in str(e.value)
    assert (tmp_path / "a.py").read_text("utf-8") == "x = 1\n"  # the edit that fit wasn't made


def test_a_text_that_appears_twice_needs_replace_all(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("n = 0\nn = 0\n", encoding="utf-8")

    with pytest.raises(ToolError, match="appears 2 times"):
        run(ctx, swap("a.py", "n = 0", "n = 1"))
    output = run(ctx, swap("a.py", "n = 0", "n = 1", replace_all=True))

    assert (tmp_path / "a.py").read_text("utf-8") == "n = 1\nn = 1\n"
    assert output.content == "Replaced 2 places in 1 file: a.py (2)."


def test_the_preview_shows_every_file_and_writes_nothing(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    edits = [swap("a.py", "x = 1", "x = 10"), swap("b.py", "y = 2", "y = 20")]

    diff = asyncio.run(
        MultiEditTool().preview(MultiEditInput.model_validate({"edits": edits}), ctx)
    )

    assert "+x = 10" in diff and "+y = 20" in diff
    assert (tmp_path / "a.py").read_text("utf-8") == "x = 1\n"


def test_the_policy_judges_each_file_as_an_edit_of_it(tmp_path: Path) -> None:
    tool = MultiEditTool()
    in_src = {"edits": [swap("src/a.py", "a", "b"), swap("src/b.py", "a", "b")]}
    with_notes = {"edits": [swap("src/a.py", "a", "b"), swap("notes.txt", "a", "b")]}

    # In auto mode it runs like Edit does, and in ask mode it asks once for the whole call.
    assert permissions(tmp_path, "auto").check(tool, in_src).decision == Decision.ALLOW
    asked = permissions(tmp_path, "ask").check(tool, in_src)
    assert asked.decision == Decision.ASK
    assert asked.rules == ("MultiEdit(src/a.py)", "MultiEdit(src/b.py)")
    assert permissions(tmp_path, "read-only").check(tool, in_src).decision == Decision.DENY

    # Rules written for Edit cover it, file by file: one refused file refuses the call.
    allowed = permissions(tmp_path, "ask", allow=["Edit(src/**)"])
    assert allowed.check(tool, in_src).decision == Decision.ALLOW
    assert allowed.check(tool, with_notes).decision == Decision.ASK
    denied = permissions(tmp_path, "auto", deny=["Edit(notes.txt)"])
    assert denied.check(tool, with_notes).decision == Decision.DENY


def test_input_that_names_no_file_is_still_judged(tmp_path: Path) -> None:
    tool = MultiEditTool()

    assert permissions(tmp_path, "ask").check(tool, {"edits": "nope"}).decision == Decision.ASK
    assert permissions(tmp_path, "read-only").check(tool, {}).decision == Decision.DENY
