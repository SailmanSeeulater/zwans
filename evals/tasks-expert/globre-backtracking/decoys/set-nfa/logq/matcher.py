"""Running a parsed pattern against a line of text.

The pattern is compiled to a small program and simulated as an NFA: the set of states the
match could be in is advanced one character at a time, so each character item is tested
at most once per position. The match reported is the leftmost one, as long as it goes.
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

    def _closure(self, states: dict, pc: int, start: int, i: int, n: int) -> None:
        program = self.program
        stack = [pc]
        while stack:
            pc = stack.pop()
            if pc in states and states[pc] <= start:
                continue
            states[pc] = start
            op = program[pc]
            kind = op[0]
            if kind == JUMP:
                stack.append(op[1])
            elif kind == SPLIT:
                stack.append(op[2])
                stack.append(op[1])
            elif kind == AT_START:
                if i == 0:
                    stack.append(pc + 1)
            elif kind == AT_END:
                if i == n:
                    stack.append(pc + 1)

    def _run(self, text: str, meter, anywhere: bool, whole: bool) -> tuple[int, int] | None:
        """Leftmost match, as long as it goes: every state is followed at once, each
        remembering the earliest start that reaches it."""
        program = self.program
        n = len(text)
        states: dict = {}
        found = None
        for i in range(n + 1):
            if found is None and (anywhere or i == 0):
                self._closure(states, 0, i, i, n)
            for pc, start in states.items():
                if program[pc][0] == MATCH and (not whole or i == n):
                    if found is None or start < found[0] or (start == found[0] and i > found[1]):
                        found = (start, i)
            if found is not None:
                states = {pc: s for pc, s in states.items() if s <= found[0]}
            if i == n or not states:
                if found is not None or not anywhere:
                    break
                continue
            following: dict = {}
            ch = text[i]
            for pc, start in sorted(states.items(), key=lambda item: item[1]):
                op = program[pc]
                if op[0] == CHAR:
                    meter.step()
                    if op[1].test(ch):
                        self._closure(following, pc + 1, start, i + 1, n)
            states = following
        return found

    def search(self, text: str, meter) -> tuple[int, int] | None:
        return self._run(text, meter, anywhere=True, whole=False)

    def fullmatch(self, text: str, meter) -> bool:
        return self._run(text, meter, anywhere=False, whole=True) is not None
