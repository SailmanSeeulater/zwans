"""The Imports tool: a project's import graph, for Python and JavaScript/TypeScript.

Questions about a codebase's structure come down to who imports whom: is there a circular
import, what does this module pull in, what would break if it changed, is this file used at
all. Grep answers them one search at a time, and misses relative imports and path aliases
(`from ..base import Tool`, `import { x } from "@/lib/api"`). This reads every source file in
a folder once, resolves its imports to the project's own files (Python modules from the
package layout, with or without `src/`; JS and TS specifiers with their extensions, index
files and the aliases in tsconfig.json or jsconfig.json), drops imports of installed
packages, and answers from the graph: counts, circular imports, modules nothing imports,
the most imported ones, or for one module what it imports and what imports it.

Python is parsed with `ast`; JavaScript and TypeScript are read with regular expressions,
which is quick and almost always right. Imports inside functions, behind `if TYPE_CHECKING:`,
`import type` and dynamic `import()` are in the graph but not in the cycles, since they
don't run when the module loads.
"""

import ast
import asyncio
import json
import posixpath
import re
import tomllib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped
from zwans.tools.hints import raise_if_missing

MAX_FILES = 5_000  # source files read
MAX_FILE_BYTES = 2_000_000  # a bigger file is generated or minified: its imports are skipped
MAX_CYCLES = 10
MAX_UNUSED = 50
TOP = 10
MAX_NEIGHBOURS = 60
PYTHON = (".py",)
JS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
CONFIGS = ("tsconfig.json", "jsconfig.json", "pyproject.toml", "package.json")
JS_TWINS = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}

FROM = re.compile(r"""\b(import|export)\s+(type\s+)?[^'";]*?\bfrom\s*(['"])([^'"\n]+)\3""")
BARE = re.compile(r"""(?m)^\s*import\s*(['"])([^'"\n]+)\1""")
DYNAMIC = re.compile(r"""\bimport\s*\(\s*(['"])([^'"\n]+)\1\s*\)""")
REQUIRE = re.compile(r"""\brequire\s*\(\s*(['"])([^'"\n]+)\1\s*\)""")
MAIN_GUARD = re.compile(r"""(?m)^if\s+__name__\s*==\s*['"]__main__['"]\s*:""")
TEST_FILE = re.compile(r"(^test_.*\.py$|_test\.py$|\.(test|spec)\.[cm]?[jt]sx?$)")
NEXT_ENTRY = re.compile(
    r"(^|/)(app/(.+/)?(page|layout|route|loading|error|not-found|template|default|"
    r"global-error|opengraph-image|icon|sitemap|robots)|pages/.+|middleware|instrumentation)"
    r"\.[cm]?[jt]sx?$"
)
CONFIG_FILE = re.compile(
    r"(^|/)([\w.-]+\.config\.[cm]?[jt]s|setup\.py|noxfile\.py|fabfile\.py|manage\.py|"
    r"conftest\.py|__main__\.py|[\w.-]+\.d\.[cm]?ts)$"
)


@dataclass
class Module:
    path: str  # relative to the workspace root
    name: str  # what it's shown as: a dotted name in Python, the path in JS
    language: Literal["python", "js"]
    entry: bool = False  # run or loaded from outside, so "nothing imports it" is expected
    imports: dict[str, bool] = field(default_factory=dict)  # path -> runs at load time
    error: str = ""


class ImportsInput(BaseModel):
    path: str = Field(
        default=".", description="The folder whose source files to read, relative to the root."
    )
    module: str = Field(
        default="",
        description='One module to look at: a file ("src/app/api.py") or a Python module '
        'name ("app.api"). Leave it empty for the whole project.',
    )


class ImportsTool:
    name = "Imports"
    description = (
        "Map a project's imports between its own files, for Python and JavaScript/TypeScript "
        "(relative imports and tsconfig path aliases resolved, installed packages left out). "
        "For the whole folder: circular imports, modules nothing imports, the most imported "
        "ones. For one module: what it imports, what imports it, and how deep its imports go. "
        "Use it before moving or splitting a module, or to untangle a circular import."
    )
    input_model = ImportsInput
    read_only = True

    async def run(self, args: ImportsInput, ctx: ToolContext) -> ToolOutput:
        folder = ctx.executor.relative(args.path)
        folder = "" if folder == "." else folder
        root = Path(getattr(ctx.executor, "root"))  # noqa: B009 (not on the Executor protocol)
        files = await _list(ctx, args.path, folder)
        sources = [f for f in files if f.endswith(PYTHON + JS)]
        if not sources:
            raise ToolError(f"There are no Python, JavaScript or TypeScript files in {args.path}.")
        cut = len(sources) > MAX_FILES
        sources = sources[:MAX_FILES]
        texts = await _read_all(ctx, sources)
        graph = Graph(root)
        await graph.add_python([p for p in sources if p.endswith(PYTHON)], texts)
        configs = await _configs(ctx, folder, files)
        graph.add_js([p for p in sources if p.endswith(JS)], texts, configs)
        await graph.mark_entries(ctx, folder, files)
        if args.module.strip():
            text = graph.about(args.module.strip())
        else:
            text = graph.summary(folder or ".")
        if cut:
            text += (
                f"\n(Only the first {MAX_FILES:,} source files were read: pass a narrower path.)"
            )
        return ToolOutput(content=text)


async def _list(ctx: ToolContext, given: str, folder: str) -> list[str]:
    argv = ["rg", "--files", "--no-require-git", "--path-separator", "/", *skipped()]
    for extension in PYTHON + JS:
        argv += ["--glob", f"*{extension}"]
    for name in CONFIGS:
        argv += ["--glob", name]
    argv.append(folder or ".")
    result = await ctx.executor.run(argv, timeout=60)
    if result.exit_code not in (0, 1):
        raise_if_missing(ctx, given, result.output)
        raise ToolError(f"Listing the files failed: {result.output.strip()}")
    return sorted(line.removeprefix("./") for line in result.output.splitlines() if line)


async def _read_all(ctx: ToolContext, paths: list[str]) -> dict[str, str]:
    limit = asyncio.Semaphore(32)

    async def one(path: str) -> tuple[str, str]:
        async with limit:
            try:
                data = await ctx.executor.read_bytes(path)
            except OSError:
                return path, ""
        if len(data) > MAX_FILE_BYTES:
            return path, ""
        return path, data.decode("utf-8", "replace")

    return dict(await asyncio.gather(*(one(path) for path in paths)))


# -- Python


def python_imports(tree: ast.Module) -> list[tuple[ast.Import | ast.ImportFrom, bool]]:
    """Each import statement, and whether it runs when the module loads (not inside a
    function or behind `if TYPE_CHECKING:`)."""
    found: list[tuple[ast.Import | ast.ImportFrom, bool]] = []

    def visit(node: ast.AST, runtime: bool) -> None:
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.append((node, runtime))
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            runtime = False
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for statement in node.body:
                visit(statement, False)
            for statement in node.orelse:
                visit(statement, runtime)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt | ast.excepthandler | ast.match_case):
                visit(child, runtime)

    visit(tree, True)
    return found


def _is_type_checking(test: ast.expr) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


@dataclass
class PythonFile:
    root: str  # the folder its module name counts from
    parts: list[str]  # its module name, split
    package: bool  # an __init__.py


class Graph:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.modules: dict[str, Module] = {}  # by path
        self._inits: dict[str, bool] = {}

    # -- building

    def _has_init(self, folder: str) -> bool:
        if folder not in self._inits:
            self._inits[folder] = (self.root / folder / "__init__.py").is_file()
        return self._inits[folder]

    def _python_file(self, path: str) -> PythonFile:
        folders = path.split("/")[:-1]
        stem = path.rsplit("/", 1)[-1].removesuffix(".py")
        top = len(folders)
        while top > 0 and self._has_init("/".join(folders[:top])):
            top -= 1
        if "src" in folders[:top]:  # a src layout with namespace packages under it
            top = len(folders[:top]) - folders[:top][::-1].index("src")
        parts = folders[top:] + ([] if stem == "__init__" else [stem])
        return PythonFile("/".join(folders[:top]), parts or [stem], stem == "__init__")

    async def add_python(self, paths: list[str], texts: dict[str, str]) -> None:
        files = {path: self._python_file(path) for path in paths}
        by_root: dict[str, dict[str, str]] = {}
        anywhere: dict[str, str] = {}
        for path, info in files.items():
            name = ".".join(info.parts)
            by_root.setdefault(info.root, {}).setdefault(name, path)
            anywhere.setdefault(name, path)
            self.modules[path] = Module(path, name, "python")

        def find(name: str, root: str, local_only: bool = False) -> str | None:
            hit = by_root.get(root, {}).get(name)
            return hit if hit or local_only else anywhere.get(name)

        def longest(name: str, root: str, local_only: bool = False) -> str | None:
            parts = name.split(".")
            for count in range(len(parts), 0, -1):
                hit = find(".".join(parts[:count]), root, local_only)
                if hit:
                    return hit
            return None

        for path, info in files.items():
            module = self.modules[path]
            text = texts.get(path, "")
            if MAIN_GUARD.search(text):
                module.entry = True
            try:
                tree = ast.parse(text, filename=path)
            except (SyntaxError, ValueError, RecursionError) as exc:
                module.error = f"couldn't be parsed: {exc}"
                continue
            for statement, runtime in python_imports(tree):
                targets: list[str | None] = []
                if isinstance(statement, ast.Import):
                    targets = [longest(alias.name, info.root) for alias in statement.names]
                elif statement.level == 0:
                    base = statement.module or ""
                    for alias in statement.names:
                        targets.append(
                            find(f"{base}.{alias.name}", info.root) or longest(base, info.root)
                        )
                else:
                    package = info.parts if info.package else info.parts[:-1]
                    up = statement.level - 1
                    if up > len(package):
                        continue  # beyond the top package
                    base_parts = package[: len(package) - up]
                    if statement.module:
                        base_parts = base_parts + statement.module.split(".")
                    base = ".".join(base_parts)
                    for alias in statement.names:
                        submodule = f"{base}.{alias.name}" if base else alias.name
                        targets.append(
                            find(submodule, info.root, True)
                            or (longest(base, info.root, True) if base else None)
                        )
                for target in targets:
                    if target and target != path:
                        self._edge(module, target, runtime)

    def _edge(self, module: Module, target: str, runtime: bool) -> None:
        module.imports[target] = module.imports.get(target, False) or runtime

    def add_js(self, paths: list[str], texts: dict[str, str], configs: "Configs") -> None:
        present = set(paths)
        for path in paths:
            self.modules[path] = Module(path, path, "js")
        for path in paths:
            module = self.modules[path]
            text = strip_comments(texts.get(path, ""))
            for specifier, runtime in js_imports(text):
                target = resolve_js(specifier, path, present, configs)
                if target and target != path:
                    self._edge(module, target, runtime)

    async def mark_entries(self, ctx: ToolContext, folder: str, files: list[str]) -> None:
        named = await _entry_points(ctx, folder, files, self.modules)
        for module in self.modules.values():
            name = module.path.rsplit("/", 1)[-1]
            if (
                module.path in named
                or _is_test(module.path)
                or CONFIG_FILE.search(module.path)
                or NEXT_ENTRY.search(module.path)
                or name == "__init__.py"
            ):
                module.entry = True

    # -- answering

    def importers(self) -> dict[str, set[str]]:
        found: dict[str, set[str]] = {path: set() for path in self.modules}
        for module in self.modules.values():
            for target in module.imports:
                found.setdefault(target, set()).add(module.path)
        return found

    def summary(self, folder: str) -> str:
        python = sum(1 for m in self.modules.values() if m.language == "python")
        js = len(self.modules) - python
        edges = sum(len(m.imports) for m in self.modules.values())
        kinds = []
        if python:
            kinds.append(f"{python} Python modules")
        if js:
            kinds.append(f"{js} JS/TS files")
        lines = [f"Imports in {folder}: {' and '.join(kinds)}, {edges} imports between them."]
        broken = [m for m in self.modules.values() if m.error]
        if broken:
            lines.append(
                f"({len(broken)} couldn't be parsed: {', '.join(m.path for m in broken[:5])})"
            )

        cycles = self.cycles()
        if cycles:
            lines.append(
                f"\nCircular imports: {len(cycles)} (imports that run when a module loads; "
                "lazy, TYPE_CHECKING and type-only imports aren't counted)"
            )
            for group, cycle in cycles[:MAX_CYCLES]:
                line = "  " + " → ".join(self.modules[p].name for p in cycle)
                if len(group) > len(cycle) - 1:
                    line += f"  ({len(group)} modules tangled together)"
                lines.append(line)
            if len(cycles) > MAX_CYCLES:
                lines.append(f"  ({len(cycles) - MAX_CYCLES} more)")
        else:
            lines.append("\nNo circular imports.")

        importers = self.importers()
        unused = sorted(
            (m for m in self.modules.values() if not importers.get(m.path) and not m.entry),
            key=lambda m: m.path,
        )
        if unused:
            lines.append(
                f"\nPossibly unused: {len(unused)} (nothing in {folder} imports them; tests, "
                "entry points and config files are left out, but code loaded by name isn't "
                "seen)"
            )
            for module in unused[:MAX_UNUSED]:
                where = f"  ({module.path})" if module.name != module.path else ""
                lines.append(f"  {module.name}{where}")
            if len(unused) > MAX_UNUSED:
                lines.append(f"  ({len(unused) - MAX_UNUSED} more)")

        ranked = sorted(
            ((len(by), path) for path, by in importers.items() if by and path in self.modules),
            key=lambda pair: (-pair[0], pair[1]),
        )
        if ranked:
            lines.append("\nMost imported:")
            width = len(str(ranked[0][0]))
            for count, target in ranked[:TOP]:
                lines.append(f"  {count:>{width}}  {self.modules[target].name}")
        lines.append("\n(Pass module for one module's imports and importers.)")
        return "\n".join(lines)

    def find(self, wanted: str) -> Module:
        wanted = wanted.strip().removeprefix("./")
        for module in self.modules.values():
            if wanted in (module.path, module.name):
                return module
        dotted = wanted.removesuffix(".py").replace("/", ".")
        suffix = [
            m
            for m in self.modules.values()
            if m.path.endswith("/" + wanted)
            or m.name.endswith("." + wanted)
            or m.name.endswith("." + dotted)
            or m.name == dotted
        ]
        if len(suffix) == 1:
            return suffix[0]
        if suffix:
            names = ", ".join(m.name for m in suffix[:10])
            raise ToolError(f"{wanted!r} could be any of: {names}. Pass the full name or path.")
        raise ToolError(
            f"No module {wanted!r} among the {len(self.modules)} source files read. Pass a "
            "file path or a dotted Python module name."
        )

    def about(self, wanted: str) -> str:
        module = self.find(wanted)
        importers = self.importers()
        title = module.name if module.name == module.path else f"{module.name} ({module.path})"
        lines = [title]
        if module.error:
            lines.append(f"(It {module.error})")
        imports = sorted(module.imports, key=lambda p: self.modules[p].name)
        lines.append(f"\nImports {len(imports)}:")
        lines += self._names(imports, module.imports)
        by = sorted(importers.get(module.path, set()), key=lambda p: self.modules[p].name)
        lines.append(f"\nImported by {len(by)}:")
        lines += self._names(by, {p: self.modules[p].imports[module.path] for p in by})
        if not by and module.entry:
            lines.append("  (none: it looks like an entry point, a test or a config file)")

        depth, reached, chain = self._deepest(module.path)
        if reached:
            lines.append(
                f"\nTransitive imports: {reached} modules, up to {depth} level"
                f"{'s' if depth != 1 else ''} deep"
            )
            if depth > 1:
                lines.append("  longest chain: " + " → ".join(self.modules[p].name for p in chain))
        else:
            lines.append("\nNo transitive imports.")
        dependents = self._reach(module.path, importers)
        if dependents:
            lines.append(f"Everything that imports it, directly or not: {dependents} modules.")
        return "\n".join(lines)

    def _names(self, paths: list[str], runtime: dict[str, bool]) -> list[str]:
        lines = []
        for path in paths[:MAX_NEIGHBOURS]:
            note = "" if runtime.get(path, True) else "  (lazy or type-only)"
            name = self.modules[path].name
            where = f"  ({path})" if name != path else ""
            lines.append(f"  {name}{where}{note}")
        if len(paths) > MAX_NEIGHBOURS:
            lines.append(f"  ({len(paths) - MAX_NEIGHBOURS} more)")
        return lines or ["  (none)"]

    def _deepest(self, start: str) -> tuple[int, int, list[str]]:
        """How deep the imports from a module go, how many it reaches, and a longest chain
        of shortest paths."""
        parent: dict[str, str | None] = {start: None}
        depth = {start: 0}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for target in self.modules[current].imports:
                if target not in parent and target in self.modules:
                    parent[target] = current
                    depth[target] = depth[current] + 1
                    queue.append(target)
        far = max(depth, key=lambda p: (depth[p], p))
        chain: list[str] = []
        node: str | None = far
        while node is not None:
            chain.append(node)
            node = parent[node]
        return depth[far], len(depth) - 1, chain[::-1]

    def _reach(self, start: str, importers: dict[str, set[str]]) -> int:
        seen = {start}
        queue = deque([start])
        while queue:
            for source in importers.get(queue.popleft(), ()):
                if source not in seen:
                    seen.add(source)
                    queue.append(source)
        return len(seen) - 1

    def cycles(self) -> list[tuple[list[str], list[str]]]:
        """Each group of modules that import one another when they load, largest first,
        with one cycle through it."""
        runtime = {
            path: [t for t, loads in m.imports.items() if loads and t in self.modules]
            for path, m in self.modules.items()
        }
        found = []
        for group in strongly_connected(runtime):
            members = set(group)
            if len(group) == 1 and group[0] not in runtime[group[0]]:
                continue
            start = min(group, key=lambda p: self.modules[p].name)
            found.append((group, _shortest_cycle(start, runtime, members)))
        found.sort(key=lambda pair: (-len(pair[0]), self.modules[pair[1][0]].name))
        return found


def strongly_connected(graph: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's algorithm, without recursion."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    groups: list[list[str]] = []
    counter = 0
    for start in graph:
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, position = work.pop()
            if position == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            targets = graph.get(node, [])
            descended = False
            for offset in range(position, len(targets)):
                target = targets[offset]
                if target not in index:
                    work.append((node, offset + 1))
                    work.append((target, 0))
                    descended = True
                    break
                if target in on_stack:
                    low[node] = min(low[node], index[target])
            if descended:
                continue
            if low[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                groups.append(group)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return groups


def _shortest_cycle(start: str, graph: dict[str, list[str]], members: set[str]) -> list[str]:
    parent: dict[str, str] = {}
    queue = deque([start])
    seen = {start}
    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target not in members:
                continue
            if target == start:
                path = [current]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                return [start, *path[::-1][1:], start]
            if target not in seen:
                seen.add(target)
                parent[target] = current
                queue.append(target)
    return [start, start]


def _is_test(path: str) -> bool:
    parts = path.split("/")
    folders = set(parts[:-1])
    return bool(TEST_FILE.search(parts[-1])) or bool(
        folders & {"tests", "test", "__tests__", "testing", "e2e"}
    )


# -- JavaScript and TypeScript


def strip_comments(text: str) -> str:
    """Code with its // and /* */ comments blanked out, strings kept."""
    out: list[str] = []
    i, n = 0, len(text)
    quote = ""
    while i < n:
        char = text[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if char == quote:
                quote = ""
            i += 1
        elif char in "'\"`":
            quote = char
            out.append(char)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            chunk = text[i : n if end < 0 else end + 2]
            out.append("\n" * chunk.count("\n") or " ")
            i += len(chunk)
        else:
            out.append(char)
            i += 1
    return "".join(out)


def js_imports(text: str) -> Iterable[tuple[str, bool]]:
    """Each specifier imported, and whether it loads with the file (not type-only, not a
    dynamic import())."""
    for match in FROM.finditer(text):
        yield match.group(4), not match.group(2)
    for match in BARE.finditer(text):
        yield match.group(2), True
    for match in REQUIRE.finditer(text):
        yield match.group(2), True
    for match in DYNAMIC.finditer(text):
        yield match.group(2), False


@dataclass
class Alias:
    pattern: str  # "@/*"
    targets: list[str]  # workspace-relative, "web/src/*"


@dataclass
class Config:
    folder: str
    aliases: list[Alias]
    base: str | None  # baseUrl, workspace-relative


type Configs = dict[str, Config]  # by folder


def parse_jsonc(text: str) -> Any:
    """JSON with comments and trailing commas, as tsconfig.json is."""
    bare = strip_comments(text)
    bare = re.sub(r",(\s*[}\]])", r"\1", bare)
    return json.loads(bare)


async def _configs(ctx: ToolContext, folder: str, files: list[str]) -> Configs:
    """tsconfig.json and jsconfig.json files in the folder and above it, by their folder."""
    candidates = [f for f in files if f.rsplit("/", 1)[-1] in ("tsconfig.json", "jsconfig.json")]
    parts = folder.split("/") if folder else []
    for count in range(len(parts) - 1, -1, -1):
        above = "/".join(parts[:count])
        for name in ("tsconfig.json", "jsconfig.json"):
            candidates.append(f"{above}/{name}" if above else name)
    configs: Configs = {}
    for path in candidates:
        here = posixpath.dirname(path)
        if here in configs:
            continue
        loaded = await _load_config(ctx, path, 0)
        if loaded is not None:
            configs[here] = loaded
    return configs


async def _load_config(ctx: ToolContext, path: str, depth: int) -> Config | None:
    try:
        data = parse_jsonc((await ctx.executor.read_bytes(path)).decode("utf-8", "replace"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    here = posixpath.dirname(path)
    inherited = Config(here, [], None)
    extends = data.get("extends")
    extended = [extends] if isinstance(extends, str) else extends
    if depth < 5 and isinstance(extended, list):
        for parent in extended:
            if isinstance(parent, str) and parent.startswith("."):
                target = posixpath.normpath(posixpath.join(here, parent))
                if not target.endswith(".json"):
                    target += ".json"
                found = await _load_config(ctx, target, depth + 1)
                if found:
                    inherited = Config(
                        here, found.aliases or inherited.aliases, found.base or inherited.base
                    )
    options = data.get("compilerOptions")
    options = options if isinstance(options, dict) else {}
    base = inherited.base
    if isinstance(options.get("baseUrl"), str):
        base = posixpath.normpath(posixpath.join(here, options["baseUrl"]))
    aliases = inherited.aliases
    paths = options.get("paths")
    if isinstance(paths, dict):
        relative_to = base if base is not None else here
        aliases = [
            Alias(
                str(pattern),
                [
                    posixpath.normpath(posixpath.join(relative_to, target))
                    for target in targets
                    if isinstance(target, str)
                ],
            )
            for pattern, targets in paths.items()
            if isinstance(targets, list)
        ]
    if not aliases and depth < 5 and isinstance(data.get("references"), list):
        for reference in data["references"]:
            if isinstance(reference, dict) and isinstance(reference.get("path"), str):
                target = posixpath.normpath(posixpath.join(here, reference["path"]))
                if not target.endswith(".json"):
                    target += "/tsconfig.json"
                found = await _load_config(ctx, target, depth + 1)
                if found and found.aliases:
                    aliases, base = found.aliases, base or found.base
                    break
    return Config(here, aliases, base)


def _nearest(path: str, configs: Configs) -> Config | None:
    folder = posixpath.dirname(path)
    while True:
        if folder in configs:
            return configs[folder]
        if not folder:
            return None
        folder = posixpath.dirname(folder)


def resolve_js(specifier: str, importer: str, present: set[str], configs: Configs) -> str | None:
    """The project file an import specifier names, or None for a package."""
    specifier = specifier.split("?", 1)[0]
    if specifier.startswith("."):
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(importer), specifier))
        return _file_for(joined, present)
    if specifier.startswith("/"):
        return None
    config = _nearest(importer, configs)
    if config is None:
        return None
    for alias in config.aliases:
        if "*" in alias.pattern:
            prefix, _, suffix = alias.pattern.partition("*")
            if specifier.startswith(prefix) and specifier.endswith(suffix):
                middle = specifier[len(prefix) : len(specifier) - len(suffix) or None]
                for target in alias.targets:
                    hit = _file_for(target.replace("*", middle, 1), present)
                    if hit:
                        return hit
        elif specifier == alias.pattern:
            for target in alias.targets:
                hit = _file_for(target, present)
                if hit:
                    return hit
    if config.base is not None:
        return _file_for(posixpath.normpath(posixpath.join(config.base, specifier)), present)
    return None


def _file_for(base: str, present: set[str]) -> str | None:
    if base.startswith("..") or base.startswith("/"):
        return None
    base = "" if base == "." else base
    candidates = [base, *(base + ext for ext in JS)]
    candidates += [f"{base}/index{ext}" if base else f"index{ext}" for ext in JS]
    stem, extension = posixpath.splitext(base)
    candidates += [stem + twin for twin in JS_TWINS.get(extension, ())]
    for candidate in candidates:
        if candidate in present:
            return candidate
    return None


# -- entry points


async def _entry_points(
    ctx: ToolContext, folder: str, files: list[str], modules: dict[str, Module]
) -> set[str]:
    """Files named as entry points: pyproject's scripts, package.json's main and bin."""
    by_name = {m.name: m.path for m in modules.values() if m.language == "python"}
    present = {m.path for m in modules.values()}
    named: set[str] = set()
    manifests = [f for f in files if f.rsplit("/", 1)[-1] in ("pyproject.toml", "package.json")]
    parts = folder.split("/") if folder else []
    for count in range(len(parts) - 1, -1, -1):
        above = "/".join(parts[:count])
        manifests += [f"{above}/{n}" if above else n for n in ("pyproject.toml", "package.json")]
    for manifest in dict.fromkeys(manifests):
        try:
            text = (await ctx.executor.read_bytes(manifest)).decode("utf-8", "replace")
        except OSError:
            continue
        here = posixpath.dirname(manifest)
        if manifest.endswith(".toml"):
            named |= _python_entries(text, by_name)
        else:
            named |= _js_entries(text, here, present)
    return named


def _python_entries(text: str, by_name: dict[str, str]) -> set[str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return set()
    found_project = data.get("project")
    project: dict[str, Any] = found_project if isinstance(found_project, dict) else {}
    targets: list[Any] = []
    for key in ("scripts", "gui-scripts"):
        table = project.get(key)
        if isinstance(table, dict):
            targets += table.values()
    groups = project.get("entry-points")
    if isinstance(groups, dict):
        for table in groups.values():
            if isinstance(table, dict):
                targets += table.values()
    tool = data.get("tool")
    poetry = tool.get("poetry") if isinstance(tool, dict) else None
    scripts = poetry.get("scripts") if isinstance(poetry, dict) else None
    if isinstance(scripts, dict):
        targets += scripts.values()
    found = set()
    for target in targets:
        if isinstance(target, str):
            name = target.split(":", 1)[0].strip()
            if name in by_name:
                found.add(by_name[name])
    return found


def _js_entries(text: str, here: str, present: set[str]) -> set[str]:
    try:
        data = json.loads(text)
    except ValueError:
        return set()
    if not isinstance(data, dict):
        return set()
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, dict):
            for inner in value.values():
                collect(inner)
        elif isinstance(value, list):
            for inner in value:
                collect(inner)

    for key in ("main", "module", "browser", "bin", "exports", "types"):
        collect(data.get(key))
    found = set()
    for value in values:
        joined = posixpath.normpath(posixpath.join(here, value))
        hit = _file_for(joined, present)
        if hit:
            found.add(hit)
    return found
