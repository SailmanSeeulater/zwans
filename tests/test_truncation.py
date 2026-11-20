import asyncio
from pathlib import Path

from zwans.context.truncation import MAX_RESULT_CHARS, fit_output
from zwans.executor.base import DROPPED_NOTE
from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolOutput


def fit(tmp_path: Path, text: str) -> str:
    executor = LocalExecutor(tmp_path / "work", spill_dir=tmp_path / "spill")
    return asyncio.run(fit_output(ToolOutput(text), "toolu_1", executor)).content


def test_a_short_result_is_left_alone(tmp_path: Path) -> None:
    assert fit(tmp_path, "short") == "short"


def test_a_long_result_is_saved_whole_and_said_so(tmp_path: Path) -> None:
    text = "x\n" * MAX_RESULT_CHARS

    shortened = fit(tmp_path, text)

    assert "characters not shown here. The full output is saved at" in shortened
    assert (tmp_path / "spill" / "toolu_1.txt").read_text(encoding="utf-8") == text


def test_output_the_command_already_dropped_isnt_promised(tmp_path: Path) -> None:
    text = "x\n" * MAX_RESULT_CHARS + DROPPED_NOTE.format(27_888_923) + "\n" + "y\n" * 10_000

    shortened = fit(tmp_path, text)

    assert "The full output" not in shortened
    assert "27,888,923 bytes from the middle were dropped while the command ran" in shortened


class _NoSearchOutside(LocalExecutor):
    """Like the jail, whose searches can't reach saved tool output."""

    def search_path(self, path: str) -> str:
        return self.relative(path)


def test_grep_is_only_suggested_where_it_can_reach_the_saved_output(tmp_path: Path) -> None:
    text = "x\n" * MAX_RESULT_CHARS
    jailed = _NoSearchOutside(tmp_path / "work", spill_dir=tmp_path / "spill")

    shortened = asyncio.run(fit_output(ToolOutput(text), "toolu_1", jailed)).content

    assert "or Grep" in fit(tmp_path, text)
    assert "Grep" not in shortened
    assert "Use Read on it, with offset and limit, to see the rest." in shortened
