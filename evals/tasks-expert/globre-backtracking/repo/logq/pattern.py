"""Compiled patterns: the API the rest of logq uses."""

from logq.matcher import Matcher
from logq.meter import UNCOUNTED
from logq.syntax import parse, size


class Pattern:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tree = parse(source)
        self.size = size(self.tree)
        self._matcher = Matcher(self.tree)

    def search(self, text: str, meter=None) -> tuple[int, int] | None:
        """The (start, end) of the match re.search would find, or None."""
        return self._matcher.search(text, meter or UNCOUNTED)

    def fullmatch(self, text: str, meter=None) -> bool:
        """Whether the whole text matches, as with re.fullmatch."""
        return self._matcher.fullmatch(text, meter or UNCOUNTED)

    def __repr__(self) -> str:
        return f"Pattern({self.source!r})"


def compile(source: str) -> Pattern:  # noqa: A001 - mirrors re.compile
    return Pattern(source)
