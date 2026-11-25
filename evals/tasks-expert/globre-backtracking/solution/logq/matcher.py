"""Running a parsed pattern against a line of text.

The pattern is compiled to a small program and run as a set of threads that advance
through the text together, one character at a time (Pike's VM). Threads are kept in
priority order, the order a backtracking matcher would try them in, and a thread that
reaches an instruction a higher-priority thread already holds at the same position is
dropped: from there both would do exactly the same. So every character item is tested at
most once per position, and the match found is the one backtracking would find.
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

    def _add(self, threads: list, seen: set, pc: int, start: int, i: int, n: int) -> None:
        """Add the thread at pc, following jumps and splits in priority order."""
        program = self.program
        stack = [pc]
        while stack:
            pc = stack.pop()
            if pc in seen:
                continue
            seen.add(pc)
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
            else:
                threads.append((pc, start))

    def _run(self, text: str, meter, anywhere: bool, whole: bool) -> tuple[int, int] | None:
        program = self.program
        n = len(text)
        threads: list = []
        seen: set = set()
        found = None
        for i in range(n + 1):
            if found is None and (anywhere or i == 0):
                self._add(threads, seen, 0, i, i, n)  # a new start, after all older ones
            if not threads:
                if found is not None or not anywhere:
                    break
                seen = set()
                continue
            following: list = []
            next_seen: set = set()
            ch = text[i] if i < n else None
            for pc, start in threads:
                op = program[pc]
                if op[0] == MATCH:
                    if whole and i != n:
                        continue
                    found = (start, i)
                    break  # the threads after this one have lower priority
                if ch is not None:
                    meter.step()
                    if op[1].test(ch):
                        self._add(following, next_seen, pc + 1, start, i + 1, n)
            threads, seen = following, next_seen
        return found

    def search(self, text: str, meter) -> tuple[int, int] | None:
        return self._run(text, meter, anywhere=True, whole=False)

    def fullmatch(self, text: str, meter) -> bool:
        return self._run(text, meter, anywhere=False, whole=True) is not None
