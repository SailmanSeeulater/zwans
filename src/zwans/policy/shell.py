"""Splits a bash command line into the simple commands it would run.

`ls && rm -rf x` is two commands, and so is `echo $(curl x)`. The policy judges each one,
so a harmless first command can't carry a harmful second one past it. Anything this parser
doesn't understand raises ShellParseError, and the policy then asks instead of guessing.
"""

import re
from dataclasses import dataclass, field

# Words that start or end a compound command. They are dropped, and what follows is a new
# simple command, so `if grep -q x f; then rm f; fi` yields `grep -q x f` and `rm f`.
KEYWORDS = frozenset({"if", "then", "elif", "else", "fi", "do", "done", "while", "until", "!"})
# Constructs whose bodies are too varied to judge word by word.
OPAQUE_KEYWORDS = frozenset({"case", "esac", "select", "function", "coproc", "[[", "]]"})
OPERATORS = ("&&", "||", ";;", "|&", ";", "|", "&", "(", ")", "\n")
REDIRECTS = ("&>>", "&>", ">>", ">|", ">&", "<&", "<>", ">", "<")


class ShellParseError(Exception):
    pass


@dataclass(frozen=True)
class Word:
    text: str
    # The shell fills part of it in when it runs ($VAR, $(...), globs), so the text
    # here isn't exactly what the program receives.
    dynamic: bool = False


@dataclass
class SimpleCommand:
    words: list[Word] = field(default_factory=list)
    redirects: list[tuple[str, Word]] = field(default_factory=list)  # (operator, target)
    # Its here-documents as written, from the marker (<<'EOF') through the closing line.
    heredocs: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


def parse(command: str) -> list[SimpleCommand]:
    """Every simple command the line runs, including those inside $(...) and `...`."""
    parser = _Parser(command)
    parser.run()
    return [c for c in parser.commands if c.words or c.redirects]


class _Parser:
    def __init__(self, source: str) -> None:
        self.s = source
        self.i = 0
        self.commands: list[SimpleCommand] = []
        self.current = SimpleCommand()
        self.pending_heredocs: list[tuple[str, bool]] = []  # (delimiter, body is expanded)
        self.heredoc_owners: list[tuple[SimpleCommand, int]] = []  # where each one is kept

    def run(self) -> None:
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t":
                self.i += 1
            elif c == "\\" and self.s.startswith("\\\n", self.i):
                self.i += 2  # a line continuation
            elif c == "#":
                end = self.s.find("\n", self.i)
                self.i = len(self.s) if end < 0 else end
            elif c == "\n" and self.pending_heredocs:
                self.i += 1
                self._read_heredocs()
                self._end_command()
            elif redirect := self._redirect():  # before operators, so &> isn't read as &
                self._read_redirect(redirect)
            elif op := self._operator():
                self.i += len(op)
                if op == "(" and self.current.words:
                    raise ShellParseError("function definitions are not checked word by word")
                self._end_command()
            else:
                self._add_word(self._read_word())
        if self.pending_heredocs:
            raise ShellParseError("a here-document has no end")
        self._end_command()

    def _operator(self) -> str | None:
        for op in OPERATORS:
            if self.s.startswith(op, self.i):
                return op
        return None

    def _redirect(self) -> str | None:
        j = self.i
        while j < len(self.s) and self.s[j].isdigit():
            j += 1
        if self.s.startswith("<<", j):
            return self.s[self.i : j + 3] if self.s.startswith("<<<", j) else self.s[self.i : j + 2]
        if self.s.startswith(("<(", ">("), j):
            return None  # process substitution, read as a word
        for op in REDIRECTS:
            if self.s.startswith(op, j):
                return self.s[self.i : j + len(op)]
        return None

    def _read_redirect(self, op: str) -> None:
        self.i += len(op)
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1
        bare = op.lstrip("0123456789")
        if bare.startswith("<<") and bare != "<<<":
            self._queue_heredoc(bare)
            return
        target = self._read_word()
        if not target.text:
            raise ShellParseError(f"{op} has no target")
        self.current.redirects.append((bare, target))

    def _queue_heredoc(self, op: str) -> None:
        if self.s.startswith("-", self.i):
            op += "-"
            self.i += 1
        start = self.i
        word = self._read_word()
        quoted = word.text != self.s[self.i - len(word.text) : self.i]  # had quotes in it
        if not word.text:
            raise ShellParseError("<< has no delimiter")
        self.pending_heredocs.append((word.text, not quoted))
        self.heredoc_owners.append((self.current, len(self.current.heredocs)))
        self.current.heredocs.append(op + self.s[start : self.i])

    def _read_heredocs(self) -> None:
        for (delimiter, expanded), (owner, index) in zip(
            self.pending_heredocs, self.heredoc_owners, strict=True
        ):
            start = self.i
            while True:
                end = self.s.find("\n", self.i)
                line = self.s[self.i : len(self.s) if end < 0 else end]
                self.i = len(self.s) if end < 0 else end + 1
                if line.strip("\t") == delimiter:
                    break
                if expanded and ("$(" in line or "`" in line):
                    raise ShellParseError("a here-document runs commands")
                if expanded:
                    _check_expansions_in(line)
                if end < 0:
                    raise ShellParseError(f"the here-document never ends with {delimiter}")
            # Kept with the body, so a rule for this command covers only this text.
            owner.heredocs[index] += "\n" + self.s[start : self.i].removesuffix("\n")
        self.pending_heredocs = []
        self.heredoc_owners = []

    def _add_word(self, word: Word) -> None:
        if not self.current.words and not word.dynamic:
            if word.text in OPAQUE_KEYWORDS:
                raise ShellParseError(f"`{word.text}` is not checked word by word")
            if word.text in KEYWORDS or word.text in ("{", "}"):
                return
            if word.text == "for":
                self._skip_for_header()
                return
        if word.text == "}" and not word.dynamic:
            self._end_command()
            return
        self.current.words.append(word)

    def _skip_for_header(self) -> None:
        """`for x in a b c` assigns a variable and runs nothing, so skip to its `do`."""
        while self.i < len(self.s) and self.s[self.i] not in ";\n":
            if self.s[self.i] in "$`":
                raise ShellParseError("the loop's list runs commands")
            self.i += 1

    def _end_command(self) -> None:
        if self.current.words or self.current.redirects:
            self.commands.append(self.current)
        self.current = SimpleCommand()

    def _read_word(self) -> Word:
        text: list[str] = []
        dynamic = False
        bracket = False
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\n;&|()<>":
                if c in "<>" and self.s.startswith("(", self.i + 1):
                    self.i += 1
                    self._substitution(self._balanced(")"))
                    text.append(c + "(...)")  # <(...) or >(...)
                    dynamic = True
                    continue
                break
            if c == "'":
                end = self.s.find("'", self.i + 1)
                if end < 0:
                    raise ShellParseError("a ' quote is never closed")
                text.append(self.s[self.i + 1 : end])
                self.i = end + 1
            elif c == '"':
                part, part_dynamic = self._double_quoted()
                text.append(part)
                dynamic = dynamic or part_dynamic
            elif c == "\\":
                text.append(self.s[self.i + 1 : self.i + 2])
                self.i += 2
            elif c == "$":
                text.append(self._dollar())
                dynamic = True
            elif c == "`":
                self._substitution(self._backticks())
                text.append("`...`")
                dynamic = True
            else:
                if c in "*?" or (c == "~" and not text):
                    dynamic = True
                elif c == "[":
                    bracket = True
                text.append(c)
                self.i += 1
        word = "".join(text)
        # [ starts a glob only when a ] closes it, so the `[` command stays a plain word
        return Word(word, dynamic or (bracket and "]" in word))

    def _double_quoted(self) -> tuple[str, bool]:
        self.i += 1
        text: list[str] = []
        dynamic = False
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(text), dynamic
            if c == "\\" and self.i + 1 < len(self.s):
                nxt = self.s[self.i + 1]
                text.append(nxt if nxt in '$`"\\\n' else c + nxt)
                self.i += 2
            elif c == "$":
                text.append(self._dollar())
                dynamic = True
            elif c == "`":
                self._substitution(self._backticks())
                text.append("`...`")
                dynamic = True
            else:
                text.append(c)
                self.i += 1
        raise ShellParseError('a " quote is never closed')

    def _dollar(self) -> str:
        """Read $NAME, ${...}, $(...) or $((...)) and return how it was written."""
        start = self.i
        self.i += 1
        if self.s.startswith("((", self.i):
            self.i += 1
            body = self._balanced(")")
            if "$(" in body or "`" in body:
                raise ShellParseError("arithmetic that runs commands")
            _check_arithmetic(body)
            if not self.s.startswith(")", self.i):
                raise ShellParseError("$(( is never closed")
            self.i += 1
        elif self.s.startswith("[", self.i):
            raise ShellParseError(ARITHMETIC_VARIABLES)  # $[...], the old $((...))
        elif self.s.startswith("(", self.i):
            self._substitution(self._balanced(")"))
            return "$(...)"
        elif self.s.startswith("{", self.i):
            body = self._balanced("}")
            if "$(" in body or "`" in body:
                raise ShellParseError("a ${...} that runs commands")
            _check_expansion(body)
        elif self.s.startswith("'", self.i):  # $'...' quoting
            end = self.s.find("'", self.i + 1)
            if end < 0:
                raise ShellParseError("a $' quote is never closed")
            self.i = end + 1
        else:
            while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] == "_"):
                self.i += 1
            if (
                self.i == start + 1
                and self.i < len(self.s)
                and self.s[self.i] in "?$!#@*-0123456789"
            ):
                self.i += 1
        return self.s[start : self.i]

    def _balanced(self, close: str) -> str:
        """Read from an opening ( or { to its matching close, skipping quoted text."""
        opener = self.s[self.i]
        depth = 0
        start = self.i + 1
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\\":
                self.i += 2
                continue
            if c == "'":
                end = self.s.find("'", self.i + 1)
                if end < 0:
                    raise ShellParseError("a ' quote is never closed")
                self.i = end + 1
                continue
            if c == '"':
                saved = self.commands, self.current
                self.commands, self.current = [], SimpleCommand()
                self._double_quoted()
                self.commands, self.current = saved
                continue
            if c == opener:
                depth += 1
            elif c == close:
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return self.s[start : self.i - 1]
            self.i += 1
        raise ShellParseError(f"a {opener} is never closed")

    def _backticks(self) -> str:
        end = self.i + 1
        while end < len(self.s) and self.s[end] != "`":
            end += 2 if self.s[end] == "\\" else 1
        if end >= len(self.s):
            raise ShellParseError("a ` quote is never closed")
        body = self.s[self.i + 1 : end]
        self.i = end + 1
        return body

    def _substitution(self, body: str) -> None:
        """Commands inside $(...), `...` and <(...) run too, so they join the list."""
        self.commands.extend(parse(body))


# Bash evaluates a variable named in arithmetic as arithmetic itself, and an array index in
# that runs any $(...) it holds: after x='a[$(rm -rf ~)]', `echo $((x))` runs rm. The same
# goes for ${s:x}, ${a[x]}, ${!x}, and ${x@P}, which expands x like a prompt.
ARITHMETIC_VARIABLES = "arithmetic on a variable, which runs any command the variable holds"
PLAIN_ARITHMETIC = re.compile(r"[\s0-9+\-*/%<>=!&|^~?:,()]*")
EXPANSION = re.compile(r"(#?)([A-Za-z_][A-Za-z0-9_]*|[0-9]+|[@*#?$!-])(\[[^\]]*\])?(.*)", re.S)
PLAIN_INDEX = re.compile(r"\[(-?[0-9]*|[@*])\]")
# The operators after a name that don't take arithmetic: ${x:-default}, ${x#prefix}, ...
TEXT_OPERATORS = (":-", ":=", ":+", ":?", "-", "=", "+", "?", "#", "%", "/", "^", ",")


def _check_arithmetic(body: str) -> None:
    """Allow arithmetic on numbers only. A name or $x in it may hold a command."""
    if not PLAIN_ARITHMETIC.fullmatch(body):
        raise ShellParseError(ARITHMETIC_VARIABLES)


def _check_expansion(body: str) -> None:
    """Refuse a ${...} that evaluates what a variable holds: an indirect ${!x} (but not
    ${!prefix*} or ${!a[@]}, which list names), a non-numeric index or offset, or @P."""
    if body.startswith("!") and body != "!":  # ${!} is the last background job
        if not body.endswith(("*", "@", "[@]", "[*]")):
            raise ShellParseError(ARITHMETIC_VARIABLES)
        return
    match = EXPANSION.fullmatch(body)
    if match is None:
        raise ShellParseError("a ${...} Zwans can't follow")
    index, rest = match.group(3), match.group(4)
    if index and not PLAIN_INDEX.fullmatch(index):
        raise ShellParseError(ARITHMETIC_VARIABLES)
    if not rest or rest.startswith(TEXT_OPERATORS):
        _check_expansions_in(rest)  # ${x:-${!y}}
        return
    if rest.startswith("@"):
        if rest[1:] in ("Q", "E", "A", "a", "U", "u", "L", "K", "k"):
            return
        raise ShellParseError("${x@P} expands x like a prompt, which can run commands")
    if rest.startswith(":"):
        _check_arithmetic(rest[1:])  # ${x:offset:length}
        return
    raise ShellParseError("a ${...} Zwans can't follow")


def _check_expansions_in(text: str) -> None:
    """Check each ${...} and $[...] in text that bash expands: a here-document's lines, or
    the default in ${x:-...}."""
    i = text.find("$")
    while 0 <= i < len(text) - 1:
        if text[i + 1] == "[":
            raise ShellParseError(ARITHMETIC_VARIABLES)
        if text[i + 1] == "{":
            depth, j = 0, i + 1
            while j < len(text):
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                if depth == 0:
                    break
                j += 1
            _check_expansion(text[i + 2 : j])
            i = j
        i = text.find("$", i + 1)
