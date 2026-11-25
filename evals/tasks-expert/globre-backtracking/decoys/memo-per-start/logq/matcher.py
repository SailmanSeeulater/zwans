"""Running a parsed pattern against a line of text.

The pattern is compiled to a small program and run by backtracking with an explicit
stack, trying choices in priority order. A (instruction, position) pair that has been
tried once is never tried again: it failed the first time, and would fail again.
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

    def _from(self, text: str, start: int, meter, whole: bool, failed: set | None):
        """Where the match starting at `start` ends, trying choices in priority order."""
        program = self.program
        n = len(text)
        stack = [(0, start)]
        while stack:
            pc, i = stack.pop()
            while True:
                if failed is not None:
                    if (pc, i) in failed:
                        break
                    failed.add((pc, i))
                op = program[pc]
                kind = op[0]
                if kind == CHAR:
                    if i < n:
                        meter.step()
                        if op[1].test(text[i]):
                            pc, i = pc + 1, i + 1
                            continue
                    break
                if kind == JUMP:
                    pc = op[1]
                elif kind == SPLIT:
                    stack.append((op[2], i))
                    pc = op[1]
                elif kind == AT_START:
                    if i != 0:
                        break
                    pc += 1
                elif kind == AT_END:
                    if i != n:
                        break
                    pc += 1
                else:
                    if whole and i != n:
                        break
                    return i
        return None

    def search(self, text: str, meter) -> tuple[int, int] | None:
        for start in range(len(text) + 1):
            end = self._from(text, start, meter, False, set())
            if end is not None:
                return start, end
        return None

    def fullmatch(self, text: str, meter) -> bool:
        return self._from(text, 0, meter, True, set()) is not None
