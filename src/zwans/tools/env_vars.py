"""The Env tool: which environment variables a project expects, and which are set. Never a value.

"KeyError: 'DATABASE_URL'" and a service that starts with an empty API key are both a
variable the code reads and nobody set. This collects the names a project uses, from its
example env files, from the code (Python, JavaScript and TypeScript, Rust, Go, Ruby, pydantic
settings classes) and from Compose files, and says for each where it's read, whether the
environment commands run in sets it, whether a .env file defines it, and whether the code
has a default. Missing ones come first.

Values are never read out: the environment and the .env files are reduced to their names
as soon as they're read, so a secret can't reach the conversation through this tool.
"""

import ast
import os
import posixpath
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from zwans.executor.local import SECRET_VARS
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped

TIMEOUT = 60
MAX_ROWS = 150
MAX_PLACES = 2
EXAMPLE_FILES = (".env.example", ".env.sample", ".env.template", ".env.dist")
DOTENV_FILES = (".env", ".env.local")
# Names any program may read, left out unless an example file lists them
SYSTEM = frozenset(
    {
        "PATH", "HOME", "USER", "USERNAME", "LOGNAME", "SHELL", "PWD", "OLDPWD", "TERM",
        "TERM_PROGRAM", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP",
        "TZ", "CI", "NODE_ENV", "EDITOR", "VISUAL", "PAGER", "HOSTNAME", "DISPLAY",
        "COLUMNS", "LINES", "NO_COLOR", "FORCE_COLOR", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
        "XDG_DATA_HOME", "XDG_RUNTIME_DIR", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
        "SYSTEMROOT", "COMSPEC", "PROGRAMFILES", "PYTHONPATH", "VIRTUAL_ENV", "CDPATH",
        "IFS", "OUT_DIR",
    }
)  # fmt: skip
SYSTEM_PREFIXES = ("CARGO_", "LC_", "npm_")  # set by cargo, the locale, npm run
NAME = r"([A-Za-z_][A-Za-z0-9_]*)"
Q = r"[\"']"
# (pattern, whether a match always has a default); group 1 is the name, a group 2 that
# matched is a default given as an argument
CODE: list[tuple[re.Pattern[str], bool]] = [
    # Python
    (re.compile(rf"environ\[\s*{Q}{NAME}{Q}\s*\]"), False),
    (re.compile(rf"environ\.get\(\s*{Q}{NAME}{Q}\s*(,\s*(?!None\s*\))[^)\s])?"), False),
    (re.compile(rf"\bgetenv\(\s*{Q}{NAME}{Q}\s*(,\s*(?!None\s*\))[^)\s])?"), False),
    # JavaScript and TypeScript
    (re.compile(rf"process\.env\.{NAME}"), False),
    (re.compile(rf"process\.env\[\s*[\"'`]{NAME}[\"'`]\s*\]"), False),
    (re.compile(rf"import\.meta\.env\.{NAME}"), False),
    # Rust
    (re.compile(rf"env::var(?:_os)?\(\s*\"{NAME}\"\s*\)"), False),
    (re.compile(rf"(?<![\w_])env!\(\s*\"{NAME}\""), False),
    (re.compile(rf"option_env!\(\s*\"{NAME}\""), True),
    # Go
    (re.compile(rf"os\.Getenv\(\s*\"{NAME}\"\s*\)"), False),
    (re.compile(rf"os\.LookupEnv\(\s*\"{NAME}\"\s*\)"), True),  # checks whether it's set
    # Ruby
    (re.compile(rf"\bENV\[\s*{Q}{NAME}{Q}\s*\]"), False),
    (re.compile(rf"\bENV\.fetch\(\s*{Q}{NAME}{Q}\s*(,|\)\s*(?:\{{|do\b))?"), False),
]
# What may follow a read to give it a default: `|| "x"`, `?? 3`, `or "x"`, `.unwrap_or(..)`
FALLBACK = re.compile(r"^\s*\)?\s*(?:\|\||\?\?|or\b|\.unwrap_or|\.ok\(\)|\.is_ok\(|\.is_err\()")
PREFILTER = (
    r"environ|getenv|process\.env|import\.meta\.env|env::var|env!|Getenv|LookupEnv"
    r"|ENV\[|ENV\.fetch|BaseSettings"
)
COMPOSE_GLOBS = ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml")
COMPOSE_NAME = re.compile(r"^(?:docker-)?compose[\w.-]*\.ya?ml$")
COMPOSE_VAR = re.compile(rf"\$\{{{NAME}(:?[-=?+])?")
RG_LINE = re.compile(r"^(.*?):(\d+):(.*)$")
DOTENV_KEY = re.compile(rf"^\s*(?:export\s+)?{NAME}\s*=")
ENV_NAME = re.compile(rf"^{NAME}=")


class EnvInput(BaseModel):
    path: str = Field(
        default=".", description="The project folder, relative to the workspace root."
    )


@dataclass
class Use:
    name: str
    places: list[str] = field(default_factory=list)
    default: bool = False
    in_example: bool = False
    in_code: bool = False


class EnvTool:
    name = "Env"
    description = (
        "List the environment variables a project expects and which of them are set, by "
        "name only: values are never shown. Names come from .env.example and similar files, "
        "the code (Python, JavaScript/TypeScript, Rust, Go, Ruby, pydantic settings) and "
        "Compose files. For each: where it's read, whether the environment commands run in "
        "sets it, whether .env or .env.local defines it, and whether the code has a default. "
        "Missing ones come first. Use it when a program fails on configuration or before "
        "running a project for the first time."
    )
    input_model = EnvInput
    read_only = True

    def __init__(self, hidden: Callable[[str], Sequence[str]] | None = None) -> None:
        # The policy's globs for files a search mustn't show (Read deny and ask rules), given
        # the folder searched, as for Grep. Such files are neither searched nor read, .env
        # files included.
        self.hidden = hidden

    async def run(self, args: EnvInput, ctx: ToolContext) -> ToolOutput:
        folder = ctx.executor.relative(args.path)
        uses: dict[str, Use] = {}
        globs = list(self.hidden(folder or ".")) if self.hidden else []
        withheld: list[str] = []  # env files the policy keeps from being read

        def use(name: str, place: str, default: bool = False, example: bool = False) -> None:
            item = uses.setdefault(name, Use(name))
            if place not in item.places:
                item.places.append(place)
            item.default = item.default or default
            item.in_example = item.in_example or example
            item.in_code = item.in_code or not example

        examples = []
        for name in EXAMPLE_FILES:
            path = _join(folder, name)
            text = None if is_hidden(path, globs) else await _read(ctx, path)
            if text is None:
                continue
            examples.append(path)
            for number, line in enumerate(text.splitlines(), 1):
                match = DOTENV_KEY.match(line)
                if match:
                    use(match.group(1), f"{path}:{number}", example=True)
            del text

        settings_files: set[str] = set()
        for path, number, text in await _search(ctx, folder, [PREFILTER], (), globs):
            if "BaseSettings" in text and path.endswith(".py"):
                settings_files.add(path)
            for name, default in code_names(text):
                use(name, f"{path}:{number}", default)
        for path in sorted(settings_files):
            source = None if is_hidden(path, globs) else await _read(ctx, path)
            if source is None:
                continue
            for name, number, default in settings_names(source):
                use(name, f"{path}:{number}", default)
        compose = await _search(ctx, folder, [r"\$\{[A-Za-z_]"], COMPOSE_GLOBS, globs)
        for path, number, text in compose:
            if not COMPOSE_NAME.match(posixpath.basename(path)):
                continue
            for name, default in compose_names(text):
                use(name, f"{path}:{number}", default)

        dotenv: dict[str, set[str]] = {}
        for name in DOTENV_FILES:
            path = _join(folder, name)
            if is_hidden(path, globs):
                if await _exists(ctx, path):
                    withheld.append(path)
                continue
            text = await _read(ctx, path)
            if text is not None:
                dotenv[path] = dotenv_names(text)
            del text  # names only from here on

        set_names = await _environment_names(ctx)
        hidden = {name for name in SECRET_VARS if name in os.environ}
        skipped_system = [n for n, u in uses.items() if _system(n) and not u.in_example]
        for name in skipped_system:
            del uses[name]

        tracked = False
        dotenv_path = _join(folder, ".env")
        if dotenv_path in dotenv or dotenv_path in withheld:
            result = await ctx.executor.run(
                ["git", "ls-files", "--error-unmatch", "--", dotenv_path], timeout=30
            )
            tracked = result.exit_code == 0
        return ToolOutput(
            content=_report(
                folder, uses, set_names, hidden, dotenv, examples, skipped_system, tracked
            )
            + _withheld_note(withheld)
        )


def _system(name: str) -> bool:
    return name in SYSTEM or name.startswith(SYSTEM_PREFIXES)


def _join(folder: str, name: str) -> str:
    return name if folder in ("", ".") else posixpath.join(folder, name)


def is_hidden(path: str, globs: Sequence[str]) -> bool:
    """Whether a path relative to the workspace root matches one of the policy's globs, read
    as ripgrep reads them (gitignore style: a glob without a slash matches a name at any
    depth, `*` stays within a folder, and a matched folder hides what's in it). Case is
    ignored, as Grep's --iglob does."""
    for glob in globs:
        pattern = re.sub(r"\\(.)", r"\1", glob)  # the policy escapes ripgrep's special letters
        anchored = "/" in pattern.rstrip("/")
        pattern = pattern.strip("/")
        regex = ""
        index = 0
        while index < len(pattern):
            if pattern.startswith("**/", index):
                regex += "(?:.*/)?"
                index += 3
            elif pattern.startswith("**", index):
                regex += ".*"
                index += 2
            elif pattern[index] == "*":
                regex += "[^/]*"
                index += 1
            elif pattern[index] == "?":
                regex += "[^/]"
                index += 1
            else:
                regex += re.escape(pattern[index])
                index += 1
        start = "^" if anchored else "^(?:.*/)?"
        if re.match(start + regex + "(?:/.*)?$", path, re.IGNORECASE):
            return True
    return False


async def _exists(ctx: ToolContext, path: str) -> bool:
    """Whether a file is there, found by listing its folder rather than reading it."""
    folder, name = posixpath.split(path)
    result = await ctx.executor.run(["ls", "-A", folder or "."], timeout=30)
    return result.exit_code == 0 and name in result.output.splitlines()


def _withheld_note(withheld: list[str]) -> str:
    if not withheld:
        return ""
    names = " and ".join(withheld)
    defines = "they define" if len(withheld) > 1 else "it defines"
    return (
        f"\nThe policy keeps {names} from being read, so whether {defines} these names isn't shown."
    )


async def _read(ctx: ToolContext, path: str) -> str | None:
    try:
        data = await ctx.executor.read_bytes(path)
    except (OSError, ValueError):
        return None
    return data.decode("utf-8", "replace")


async def _search(
    ctx: ToolContext,
    folder: str,
    patterns: list[str],
    globs: tuple[str, ...],
    hidden: Sequence[str] = (),
) -> list[tuple[str, int, str]]:
    """Lines matching any of the patterns, as (path, line number, text)."""
    argv = ["rg", "--color", "never", "--no-require-git", "--path-separator", "/"]
    argv += ["--max-columns", "1000", "--line-number", "--no-heading", "--with-filename"]
    argv += ["--sort", "path", *skipped(*globs)]
    for glob in globs:
        argv += ["--glob", glob]
    # The env files are read for their names only, never searched line by line
    for name in (*DOTENV_FILES, ".env.*"):
        argv += ["--glob", f"!{name}"]
    # Last, since a later glob wins over an earlier one
    for glob in hidden:
        argv += ["--iglob", f"!{glob}"]
    for pattern in patterns:
        argv += ["--regexp", pattern]
    argv.append(folder or ".")
    result = await ctx.executor.run(argv, timeout=TIMEOUT)
    if result.exit_code == 1:  # nothing matched
        return []
    if result.exit_code != 0:
        raise ToolError(f"Searching the code failed: {result.output.strip()[:500]}")
    found = []
    for line in result.output.splitlines():
        match = RG_LINE.match(line)
        if match:
            found.append((match.group(1).removeprefix("./"), int(match.group(2)), match.group(3)))
    return found


def code_names(line: str) -> list[tuple[str, bool]]:
    """The variable names a line of code reads, each with whether it gives a default."""
    found = []
    for pattern, always in CODE:
        for match in pattern.finditer(line):
            given = match.lastindex is not None and match.lastindex >= 2 and match.group(2)
            after = bool(FALLBACK.match(line[match.end() :]))
            found.append((match.group(1), always or bool(given) or after))
    return found


def compose_names(line: str) -> list[tuple[str, bool]]:
    """Names in ${X}, ${X:-default} and ${X-default} of a Compose file; "?" means required."""
    if line.lstrip().startswith("#"):
        return []
    return [
        (match.group(1), (match.group(2) or "").lstrip(":") in ("-", "="))
        for match in COMPOSE_VAR.finditer(line)
    ]


def dotenv_names(text: str) -> set[str]:
    return {match.group(1) for line in text.splitlines() if (match := DOTENV_KEY.match(line))}


def settings_names(source: str) -> list[tuple[str, int, bool]]:
    """The variables pydantic settings classes read: each field's name upper-cased, after
    the class's env_prefix when it's a literal, or the field's alias. Best effort."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    classes = sorted(
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)),
        key=lambda node: node.lineno,
    )
    settings = {"BaseSettings"}
    found = []
    for node in classes:
        if not any(_base_name(base) in settings for base in node.bases):
            continue
        settings.add(node.name)
        prefix = _env_prefix(node)
        for item in node.body:
            if not isinstance(item, ast.AnnAssign) or not isinstance(item.target, ast.Name):
                continue
            field_name = item.target.id
            if field_name.startswith("_") or field_name == "model_config":
                continue
            alias, default = _field_call(item.value)
            name = alias or (prefix + field_name).upper()
            found.append((name, item.lineno, default))
    return found


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    return ""


def _env_prefix(node: ast.ClassDef) -> str:
    for item in node.body:
        # model_config = SettingsConfigDict(env_prefix="APP_") or {"env_prefix": "APP_"}
        if isinstance(item, ast.Assign | ast.AnnAssign) and item.value is not None:
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            if any(isinstance(t, ast.Name) and t.id == "model_config" for t in targets):
                value = item.value
                if isinstance(value, ast.Call):
                    for keyword in value.keywords:
                        if keyword.arg == "env_prefix" and _literal(keyword.value):
                            return _literal(keyword.value)
                if isinstance(value, ast.Dict):
                    for key, entry in zip(value.keys, value.values, strict=True):
                        if key is not None and _literal(key) == "env_prefix":
                            return _literal(entry)
        # class Config: env_prefix = "APP_"
        if isinstance(item, ast.ClassDef) and item.name == "Config":
            for inner in item.body:
                if (
                    isinstance(inner, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "env_prefix" for t in inner.targets)
                    and _literal(inner.value)
                ):
                    return _literal(inner.value)
    return ""


def _field_call(value: ast.expr | None) -> tuple[str, bool]:
    """A field's alias, if it's a literal, and whether it has a default."""
    if value is None:
        return "", False
    if not (isinstance(value, ast.Call) and _base_name(value.func) == "Field"):
        return "", True
    alias = ""
    default = False
    if value.args:
        first = value.args[0]
        default = not (isinstance(first, ast.Constant) and first.value is Ellipsis)
    for keyword in value.keywords:
        if keyword.arg in ("alias", "validation_alias") and _literal(keyword.value):
            alias = _literal(keyword.value)
        if keyword.arg in ("default", "default_factory"):
            default = True
    return alias, default


def _literal(node: ast.expr) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


async def _environment_names(ctx: ToolContext) -> set[str]:
    """The names set in the environment commands run in. The values are dropped here."""
    result = await ctx.executor.run(["env"], timeout=30)
    if result.exit_code != 0:
        return set()
    return {
        match.group(1) for line in result.output.splitlines() if (match := ENV_NAME.match(line))
    }


def _report(
    folder: str,
    uses: dict[str, Use],
    set_names: set[str],
    hidden: set[str],
    dotenv: dict[str, set[str]],
    examples: list[str],
    skipped_system: list[str],
    tracked: bool,
) -> str:
    where = "the workspace" if folder in ("", ".") else folder
    if not uses:
        lines = [f"No environment variables found in {where}."]
        if skipped_system:
            lines.append(f"(Left out common system ones: {', '.join(sorted(skipped_system))}.)")
        return "\n".join(lines)

    groups: dict[str, list[list[str]]] = {"missing": [], "set": [], "default": []}
    for name in sorted(uses):
        item = uses[name]
        notes = [f"in {path}" for path, names in dotenv.items() if name in names]
        if name in hidden:
            notes.append("set for Zwans but removed from commands")
        if item.in_example and not item.in_code:
            notes.append("only in the example file")
        places = item.places[:MAX_PLACES]
        if len(item.places) > MAX_PLACES:
            places.append(f"+{len(item.places) - MAX_PLACES}")
        row = [name, ", ".join(places), "; ".join(notes)]
        if name in set_names:
            groups["set"].append(row)
        elif item.default:
            groups["default"].append(row)
        else:
            groups["missing"].append(row)

    lines = [
        f"{len(uses)} environment variables used in {where}. Names only; values are never shown."
    ]
    if tracked:
        lines.append(
            "WARNING: .env is tracked by git, so whatever it holds is in the repository's "
            "history. It usually belongs in .gitignore."
        )
    titles = {
        "missing": "Missing: used, not set, no default",
        "set": "Set in the environment commands run in",
        "default": "Not set, but the code has a default or handles it being unset",
    }
    shown = 0
    for key, title in titles.items():
        rows = groups[key]
        if not rows:
            continue
        lines += ["", f"{title} ({len(rows)}):"]
        room = max(MAX_ROWS - shown, 0)
        width = max(len(row[0]) for row in rows[:room]) if rows[:room] else 0
        used_width = max(len(row[1]) for row in rows[:room]) if rows[:room] else 0
        for row in rows[:room]:
            text = f"  {row[0].ljust(width)}  {row[1].ljust(used_width)}  {row[2]}"
            lines.append(text.rstrip())
        if len(rows) > room:
            lines.append(f"  ({len(rows) - room} more not shown. Give a narrower path.)")
        shown += min(len(rows), room)

    sources = ["code", *examples, *(f"{path} (names)" for path in dotenv)]
    lines += ["", "Read: " + ", ".join(sources) + "."]
    if any(uses[name].in_code for name in uses) and not examples:
        lines.append("There is no .env.example listing them.")
    if hidden & set(uses):
        lines.append("Zwans removes its own API keys from the environment of the commands it runs.")
    if skipped_system:
        lines.append(f"Left out common system names: {', '.join(sorted(skipped_system))}.")
    return "\n".join(lines)
