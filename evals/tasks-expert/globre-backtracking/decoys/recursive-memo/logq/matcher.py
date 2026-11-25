"""Running a parsed pattern against a line of text.

The pattern is compiled to a small program and run by backtracking in priority order,
remembering every (instruction, position) pair that failed so no work is ever repeated.
"""

from logq.syntax import Alt, Char, End, Node, Repeat, Seq, Start

CHAR, SPLIT, JUMP, AT_START, AT_END, MATCH = range(6)


class Matcher:
    """Matches one pattern. Built once per pattern by compile()."""

    def __init__(self, node: Node) -> None:
        self.node = node
        self.program: list[list] = []
        self._emit(node)
        self.program.append([MATCH])

    # -- compiling

    def _emit(self, node: Node) -> None:
        program = self.program
        match node:
            case Char():
                program.append([CHAR, node])
            case Start():
                program.append([AT_START])
            case End():
                program.append([AT_END])
            case Seq(items):
                for item in items:
                    self._emit(item)
            case Alt(options):
                jumps = []
                for option in options[:-1]:
                    split = len(program)
                    program.append([SPLIT, split + 1, None])
                    self._emit(option)
                    jumps.append(len(program))
                    program.append([JUMP, None])
                    program[split][2] = len(program)
                self._emit(options[-1])
                for jump in jumps:
                    program[jump][1] = len(program)
            case Repeat(item, low, high):
                for _ in range(low):
                    self._emit(item)
                if high is None:
                    # item*: try another one first, else go on
                    loop = len(program)
                    program.append([SPLIT, loop + 1, None])
                    self._emit(item)
                    program.append([JUMP, loop])
                    program[loop][2] = len(program)
                else:
                    # up to high - low more, each one only if the one before was taken
                    splits = []
                    for _ in range(high - low):
                        splits.append(len(program))
                        program.append([SPLIT, len(program) + 1, None])
                        self._emit(item)
                    for split in splits:
                        program[split][2] = len(program)
            case _:
                raise TypeError(node)

    # -- running

    def _from(self, text: str, pc: int, i: int, meter, whole: bool, failed: set):
        """Where the match from instruction pc at position i ends, or None. Pairs that
        failed once are remembered: they fail again from any start."""
        if (pc, i) in failed:
            return None
        op = self.program[pc]
        kind = op[0]
        end = None
        if kind == CHAR:
            if i < len(text):
                meter.step()
                if op[1].test(text[i]):
                    end = self._from(text, pc + 1, i + 1, meter, whole, failed)
        elif kind == JUMP:
            end = self._from(text, op[1], i, meter, whole, failed)
        elif kind == SPLIT:
            end = self._from(text, op[1], i, meter, whole, failed)
            if end is None:
                end = self._from(text, op[2], i, meter, whole, failed)
        elif kind == AT_START:
            if i == 0:
                end = self._from(text, pc + 1, i, meter, whole, failed)
        elif kind == AT_END:
            if i == len(text):
                end = self._from(text, pc + 1, i, meter, whole, failed)
        elif not whole or i == len(text):
            end = i
        if end is None:
            failed.add((pc, i))
        return end

    def search(self, text: str, meter) -> tuple[int, int] | None:
        failed: set = set()
        for start in range(len(text) + 1):
            end = self._from(text, 0, start, meter, False, failed)
            if end is not None:
                return start, end
        return None

    def fullmatch(self, text: str, meter) -> bool:
        return self._from(text, 0, 0, meter, True, set()) is not None
