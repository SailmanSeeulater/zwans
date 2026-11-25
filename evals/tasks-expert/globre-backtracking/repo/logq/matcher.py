"""Running a parsed pattern against a line of text."""

from collections.abc import Callable

from logq.syntax import Alt, Char, End, Node, Repeat, Seq, Start

# A continuation: given the position reached, finish the match from there and return
# where it ends, or None if it can't be finished.
Then = Callable[[int], int | None]


class Matcher:
    """Matches one pattern. Built once per pattern by compile()."""

    def __init__(self, node: Node) -> None:
        self.node = node

    def search(self, text: str, meter) -> tuple[int, int] | None:
        for start in range(len(text) + 1):
            end = self._match(self.node, text, start, lambda i: i, meter)
            if end is not None:
                return start, end
        return None

    def fullmatch(self, text: str, meter) -> bool:
        whole = len(text)
        end = self._match(self.node, text, 0, lambda i: i if i == whole else None, meter)
        return end is not None

    def _match(self, node: Node, text: str, i: int, then: Then, meter) -> int | None:
        """Match `node` at position i, trying its choices in order (the first alternative
        first, repeats taking as many as they can) until `then` accepts where it ends."""
        match node:
            case Char():
                if i < len(text):
                    meter.step()
                    if node.test(text[i]):
                        return then(i + 1)
                return None
            case Start():
                return then(i) if i == 0 else None
            case End():
                return then(i) if i == len(text) else None
            case Seq(items):
                return self._sequence(items, 0, text, i, then, meter)
            case Alt(options):
                for option in options:
                    end = self._match(option, text, i, then, meter)
                    if end is not None:
                        return end
                return None
            case Repeat(item, low, high):
                return self._repeat(item, low, high, 0, text, i, then, meter)
        raise TypeError(node)

    def _sequence(self, items, index: int, text: str, i: int, then: Then, meter) -> int | None:
        if index == len(items):
            return then(i)
        return self._match(
            items[index], text, i,
            lambda j: self._sequence(items, index + 1, text, j, then, meter),
            meter,
        )

    def _repeat(self, item, low, high, count, text, i, then, meter) -> int | None:
        if high is None or count < high:
            end = self._match(
                item, text, i,
                lambda j: self._repeat(item, low, high, count + 1, text, j, then, meter),
                meter,
            )
            if end is not None:
                return end
        if count >= low:
            return then(i)
        return None
