"""Reading Strata configuration files. SPEC.md at the project root defines the format."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

NAME = r"[A-Za-z_][A-Za-z0-9_-]*"
PATH_RE = re.compile(rf"{NAME}(?:\.{NAME})*")
INTEGER_RE = re.compile(r"-?(?:0|[1-9](?:_?[0-9])*)")
ASSIGN_RE = re.compile(rf"({NAME}(?:\.{NAME})*)\s*(\+=|\?=|=)(.*)", re.DOTALL)
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class ConfigError(Exception):
    """A configuration that cannot be read. `file` and `line` say where, when known."""

    def __init__(self, message: str, file: Path | None = None, line: int | None = None):
        where = ""
        if file is not None:
            where = f"{file}:{line}: " if line is not None else f"{file}: "
        super().__init__(where + message)
        self.message = message
        self.file = file
        self.line = line


@dataclass(frozen=True)
class Ref:
    kind: str  # "abs", "rel" or "env"
    path: tuple[str, ...] = ()
    env_name: str = ""
    fallback: str | None = None


@dataclass
class Val:
    kind: str  # "lit", "text", "whole" or "list"
    data: object
    file: Path
    line: int
    section: tuple[str, ...]
    is_item: bool = False
    items: list["Val"] = field(default_factory=list)


class _Syntax(Exception):
    """A problem found while parsing one line; turned into a ConfigError with its location."""


def _is_comment_start(text: str, i: int) -> bool:
    return text[i] == "#" and i > 0 and text[i - 1] in " \t"


def _strip_trailing_comment(text: str) -> str:
    # For lines whose structure cannot contain quotes (headers and @unset).
    for i in range(len(text)):
        if _is_comment_start(text, i):
            return text[:i].rstrip()
    return text.rstrip()


def _check_rest(rest: str) -> None:
    if rest.strip() == "":
        return
    if rest[0] in " \t" and rest.lstrip().startswith("#"):
        return
    raise _Syntax(f"unexpected text after the value: {rest.strip()!r}")


def _parse_ref(body: str) -> Ref:
    if body.startswith("env:"):
        spec = body[4:]
        fallback = None
        if ":-" in spec:
            spec, fallback = spec.split(":-", 1)
        if not ENV_NAME_RE.fullmatch(spec):
            raise _Syntax(f"bad environment variable name in ${{{body}}}")
        return Ref("env", env_name=spec, fallback=fallback)
    if body.startswith("."):
        if not PATH_RE.fullmatch(body[1:]):
            raise _Syntax(f"bad reference ${{{body}}}")
        return Ref("rel", path=tuple(body[1:].split(".")))
    if not PATH_RE.fullmatch(body):
        raise _Syntax(f"bad reference ${{{body}}}")
    return Ref("abs", path=tuple(body.split(".")))


def _interpolate(text: str) -> list[object]:
    """Split text into literal strings and Refs."""
    parts: list[object] = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "$" and i + 1 < len(text) and text[i + 1] == "$":
            buf.append("$")
            i += 2
        elif ch == "$" and i + 1 < len(text) and text[i + 1] == "{":
            end = text.find("}", i + 2)
            if end == -1:
                raise _Syntax("unterminated ${")
            if buf:
                parts.append("".join(buf))
                buf = []
            parts.append(_parse_ref(text[i + 2 : end]))
            i = end + 1
        else:
            buf.append(ch)
            i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def _scan_double(text: str, start: int) -> tuple[list[object], int]:
    """Parse a double-quoted string starting at text[start] == '"'. Returns (parts, index after)."""
    parts: list[object] = []
    buf: list[str] = []
    i = start + 1
    escapes = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "$": "$"}
    while True:
        if i >= len(text):
            raise _Syntax("unterminated double-quoted string")
        ch = text[i]
        if ch == '"':
            break
        if ch == "\\":
            if i + 1 >= len(text) or text[i + 1] not in escapes:
                raise _Syntax("unknown escape in double-quoted string")
            buf.append(escapes[text[i + 1]])
            i += 2
            continue
        if ch == "$":
            # Collect the unescaped run and interpolate it on its own.
            j = i
            run: list[str] = []
            while j < len(text) and text[j] not in '"\\':
                if text[j] == "$" and j + 1 < len(text) and text[j + 1] == "{":
                    end = text.find("}", j + 2)
                    if end == -1:
                        raise _Syntax("unterminated ${")
                    run.append(text[j : end + 1])
                    j = end + 1
                else:
                    run.append(text[j])
                    j += 1
            for part in _interpolate("".join(run)):
                if isinstance(part, str):
                    buf.append(part)
                else:
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    parts.append(part)
            i = j
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts, i + 1


def _scan_single(text: str, start: int) -> tuple[str, int]:
    end = text.find("'", start + 1)
    if end == -1:
        raise _Syntax("unterminated single-quoted string")
    return text[start + 1 : end], end + 1


def _text_val(parts: list[object]) -> tuple[str, object]:
    if not parts:
        return "lit", ""
    if all(isinstance(p, str) for p in parts):
        return "lit", "".join(parts)  # type: ignore[arg-type]
    return "text", parts


def _bare(text: str) -> tuple[str, object]:
    if text == "":
        return "lit", ""
    if text == "true":
        return "lit", True
    if text == "false":
        return "lit", False
    if INTEGER_RE.fullmatch(text):
        return "lit", int(text.replace("_", ""))
    parts = _interpolate(text)
    if len(parts) == 1 and isinstance(parts[0], Ref):
        return "whole", parts[0]
    return _text_val(parts)


def _parse_value(text: str) -> tuple[str, object]:
    """Return (kind, data) for the value text (leading whitespace already removed)."""
    if text.startswith('"'):
        parts, end = _scan_double(text, 0)
        _check_rest(text[end:])
        return _text_val(parts)
    if text.startswith("'"):
        literal, end = _scan_single(text, 0)
        _check_rest(text[end:])
        return "lit", literal
    if text.startswith("["):
        items: list[tuple[str, object]] = []
        i = 1
        while True:
            while i < len(text) and text[i] in " \t":
                i += 1
            if i >= len(text):
                raise _Syntax("unterminated list")
            if text[i] == "]":
                i += 1
                break
            ch = text[i]
            if ch == ",":
                raise _Syntax("empty list item")
            if ch == "[":
                raise _Syntax("lists cannot be nested")
            if ch == '"':
                parts, i = _scan_double(text, i)
                items.append(_text_val(parts))
            elif ch == "'":
                literal, i = _scan_single(text, i)
                items.append(("lit", literal))
            else:
                j = i
                while j < len(text) and text[j] not in ",]" and not _is_comment_start(text, j):
                    j += 1
                if j < len(text) and _is_comment_start(text, j):
                    raise _Syntax("unterminated list")
                items.append(_bare(text[i:j].strip()))
                i = j
            while i < len(text) and text[i] in " \t":
                i += 1
            if i >= len(text):
                raise _Syntax("unterminated list")
            if text[i] == ",":
                i += 1
            elif text[i] == "]":
                i += 1
                break
            else:
                raise _Syntax("expected ',' or ']' in list")
        _check_rest(text[i:])
        return "list", items
    for i in range(len(text)):
        if _is_comment_start(text, i):
            text = text[:i]
            break
    return _bare(text.rstrip())


class _Loader:
    def __init__(self, env: Mapping[str, str]):
        self.env = env
        self.root: dict = {}
        self.stack: list[Path] = []

    # -- the tree -------------------------------------------------------------------------

    def _table(self, path: tuple[str, ...]) -> dict:
        node = self.root
        for name in path:
            child = node.get(name)
            if child is None:
                child = node[name] = {}
            elif not isinstance(child, dict):
                raise _Syntax(f"{'.'.join(path)}: {name} is a value, not a table")
            node = child
        return node

    def _lookup(self, path: tuple[str, ...]) -> object:
        node: object = self.root
        for name in path:
            if not isinstance(node, dict) or name not in node:
                return None
            node = node[name]
        return node

    # -- reading ---------------------------------------------------------------------------

    def read(self, file: Path, base: tuple[str, ...]) -> None:
        resolved = file.resolve()
        self.stack.append(resolved)
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            self.stack.pop()
            raise ConfigError(f"cannot read {file}: {exc}", resolved, None) from exc
        current = base
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line[0] in "#;":
                continue
            try:
                current = self._line(line, resolved, number, base, current)
            except _Syntax as exc:
                raise ConfigError(str(exc), resolved, number) from None
        self.stack.pop()

    def _line(
        self, line: str, file: Path, number: int, base: tuple[str, ...], current: tuple[str, ...]
    ) -> tuple[str, ...]:
        if line.startswith("["):
            body = _strip_trailing_comment(line)
            if not body.endswith("]"):
                raise _Syntax("bad section header")
            inner = body[1:-1].strip()
            if inner == "":
                return base
            if not PATH_RE.fullmatch(inner):
                raise _Syntax(f"bad section name {inner!r}")
            section = base + tuple(inner.split("."))
            self._table(section)
            return section
        if line.startswith("@"):
            self._directive(line, file, number, current)
            return current
        match = ASSIGN_RE.fullmatch(line)
        if not match:
            raise _Syntax(f"cannot read line: {line!r}")
        target = current + tuple(match.group(1).split("."))
        op = match.group(2)
        kind, data = _parse_value(match.group(3).lstrip())
        if kind == "list":
            items = [Val(k, d, file, number, current, is_item=True) for k, d in data]  # type: ignore[union-attr]
            value = Val("list", None, file, number, current, items=items)
        else:
            value = Val(kind, data, file, number, current)
        self._assign(target, op, value)
        return current

    def _assign(self, target: tuple[str, ...], op: str, value: Val) -> None:
        parent = self._table(target[:-1])
        key = target[-1]
        existing = parent.get(key)
        if isinstance(existing, dict):
            raise _Syntax(f"{'.'.join(target)} is a table, not a value")
        if op == "=":
            parent[key] = value
        elif op == "?=":
            if existing is None:
                parent[key] = value
        else:
            if value.kind == "list":
                new_items = list(value.items)
            else:
                value.is_item = True
                new_items = [value]
            if existing is None:
                parent[key] = Val(
                    "list", None, value.file, value.line, value.section, items=new_items
                )
            elif existing.kind == "list":
                parent[key] = Val(
                    "list",
                    None,
                    existing.file,
                    existing.line,
                    existing.section,
                    items=existing.items + new_items,
                )
            else:
                raise _Syntax(f"cannot append to {'.'.join(target)}: it is not a list")

    def _directive(self, line: str, file: Path, number: int, current: tuple[str, ...]) -> None:
        match = re.match(r"@(include\??|unset)(?=\s|$)(.*)", line, re.DOTALL)
        if not match:
            raise _Syntax(f"unknown directive: {line.split()[0]}")
        name, arg = match.group(1), match.group(2).strip()
        if name == "unset":
            arg = _strip_trailing_comment(arg)
            if not PATH_RE.fullmatch(arg):
                raise _Syntax("@unset needs a path")
            path = current + tuple(arg.split("."))
            parent = self._lookup(path[:-1])
            if isinstance(parent, dict):
                parent.pop(path[-1], None)
            return
        if not arg.startswith('"'):
            raise _Syntax("@include needs a double-quoted file name")
        end = arg.find('"', 1)
        if end == -1:
            raise _Syntax("unterminated file name")
        name_text = arg[1:end]
        if "\\" in name_text or "$" in name_text:
            raise _Syntax("file names cannot contain escapes or references")
        _check_rest(arg[end + 1 :])
        target = (file.parent / name_text).resolve()
        if target in self.stack:
            raise _Syntax(f"include cycle: {name_text} is already being read")
        if not target.is_file():
            if name == "include?":
                return
            raise _Syntax(f"included file not found: {name_text}")
        self.read(target, current)

    # -- resolving -------------------------------------------------------------------------

    def resolve(self) -> dict:
        self.active: set[int] = set()
        self.done: dict[int, object] = {}
        return self._resolve_table(self.root)

    def _resolve_table(self, table: dict) -> dict:
        result = {}
        for key, node in table.items():
            if isinstance(node, dict):
                result[key] = self._resolve_table(node)
            else:
                value = self._resolve(node)
                result[key] = list(value) if isinstance(value, list) else value
        return result

    def _resolve(self, val: Val) -> object:
        key = id(val)
        if key in self.done:
            return self.done[key]
        if key in self.active:
            raise ConfigError("reference cycle", val.file, val.line)
        self.active.add(key)
        try:
            result = self._compute(val)
        finally:
            self.active.discard(key)
        self.done[key] = result
        return result

    def _compute(self, val: Val) -> object:
        if val.kind == "lit":
            return val.data
        if val.kind == "list":
            return [self._resolve(item) for item in val.items]
        if val.kind == "whole":
            target = self._target(val, val.data)  # type: ignore[arg-type]
            if val.is_item and isinstance(target, (list, dict)):
                raise ConfigError("a list item cannot be a list or a table", val.file, val.line)
            if isinstance(target, list):
                return list(target)
            return target
        pieces = []
        for part in val.data:  # type: ignore[union-attr]
            if isinstance(part, str):
                pieces.append(part)
                continue
            target = self._target(val, part)
            if isinstance(target, bool):
                pieces.append("true" if target else "false")
            elif isinstance(target, (int, str)):
                pieces.append(str(target))
            else:
                raise ConfigError("cannot put a list or a table into text", val.file, val.line)
        return "".join(pieces)

    def _target(self, val: Val, ref: Ref) -> object:
        if ref.kind == "env":
            if ref.env_name in self.env:
                return self.env[ref.env_name]
            if ref.fallback is not None:
                return ref.fallback
            raise ConfigError(f"environment variable {ref.env_name} is not set", val.file, val.line)
        path = ref.path if ref.kind == "abs" else val.section + ref.path
        node = self._lookup(path)
        if node is None:
            raise ConfigError(f"reference to missing {'.'.join(path)}", val.file, val.line)
        if isinstance(node, dict):
            if val.kind != "whole" or val.is_item:
                raise ConfigError(f"{'.'.join(path)} is a table", val.file, val.line)
            return self._resolve_table(node)
        return self._resolve(node)


def load(path: str | os.PathLike[str], env: Mapping[str, str] | None = None) -> dict:
    """Read the Strata configuration at `path` and everything it includes."""
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"configuration file not found: {file}", file, None)
    loader = _Loader(os.environ if env is None else env)
    loader.read(file, ())
    return loader.resolve()
