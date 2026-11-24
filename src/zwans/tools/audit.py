"""The Audit tool: which of the project's pinned dependencies have known vulnerabilities.

A lockfile pins hundreds of packages, most of which nobody chose by hand, and a model can't
know which of those versions have advisories published since its training. This reads the
project's lockfiles (Python, JavaScript, Rust, Go and Ruby ones), asks OSV.dev about every
pinned version in a few batched requests, then fetches the advisories it found for their
summaries, severities and the versions that fix them. The vulnerable packages come most
severe first, each with the version to move to.

Like Packages, the policy judges a call as a network request to OSV.dev's host.
"""

import asyncio
import json
import math
import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Any

import httpx
from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.grep import skipped
from zwans.tools.packages import version_key

HOST = "api.osv.dev"
QUERY_BATCH = f"https://{HOST}/v1/querybatch"
VULN = f"https://{HOST}/v1/vulns/"
USER_AGENT = "Zwans (a coding agent auditing its user's dependencies)"
TIMEOUT = 30.0
BATCH = 1000  # queries in one querybatch request, OSV.dev's limit
MAX_DETAILS = 40  # advisories fetched in full
PARALLEL = 6  # advisory fetches at once
MAX_FILES = 30  # lockfiles read from a folder
MAX_PACKAGES = 60  # vulnerable packages listed
MAX_OUTPUT = 16_000
MAX_SUMMARY = 200

FIXED_NAMES = {
    "uv.lock": "PyPI",
    "poetry.lock": "PyPI",
    "Pipfile.lock": "PyPI",
    "Cargo.lock": "crates.io",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "npm",
    "pnpm-lock.yaml": "npm",
    "go.sum": "Go",
    "Gemfile.lock": "RubyGems",
}
REQUIREMENTS = re.compile(r"^requirements.*\.txt$")
LABEL_SCORES = {"CRITICAL": 9.5, "HIGH": 8.0, "MODERATE": 5.5, "MEDIUM": 5.5, "LOW": 2.0}


class AuditInput(BaseModel):
    path: str = Field(
        default=".",
        description="A lockfile (uv.lock, poetry.lock, requirements.txt, Pipfile.lock, "
        "package-lock.json, yarn.lock, pnpm-lock.yaml, Cargo.lock, go.sum, Gemfile.lock), or "
        "a folder to look for them in, two levels down at most. Relative to the workspace root.",
    )


@dataclass(frozen=True)
class Dep:
    ecosystem: str
    name: str
    version: str


@dataclass
class Lockfile:
    path: str
    deps: list[Dep]
    note: str = ""  # such as unpinned lines skipped


@dataclass
class Advisory:
    id: str
    names: list[str]  # the id first, then the aliases worth showing
    summary: str = ""
    score: float = 0.0  # for ordering: a CVSS base score, or one guessed from the label
    severity: str = ""  # as shown: "HIGH 7.5", "MODERATE"
    fixed: list[str] = field(default_factory=list)
    last_affected: list[str] = field(default_factory=list)
    detailed: bool = False


class AuditTool:
    name = "Audit"
    description = (
        "Check every pinned dependency in the project's lockfiles against OSV.dev's database "
        "of known vulnerabilities: Python (uv.lock, poetry.lock, requirements*.txt, "
        "Pipfile.lock), JavaScript (package-lock.json, yarn.lock, pnpm-lock.yaml), Rust "
        "(Cargo.lock), Go (go.sum) and Ruby (Gemfile.lock). Lists the vulnerable packages, "
        "most severe first, with each advisory's summary and the version that fixes it. Use "
        "it before a release, after adding dependencies, or when asked whether the project "
        "is affected by an advisory."
    )
    input_model = AuditInput
    read_only = False  # it sends a request out, which the policy judges like a network command

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    def host(self, args: dict[str, Any]) -> str:
        return HOST

    async def run(self, args: AuditInput, ctx: ToolContext) -> ToolOutput:
        lockfiles = await _lockfiles(args.path or ".", ctx)
        queries: dict[Dep, list[str]] = {}
        for lockfile in lockfiles:
            for dep in lockfile.deps:
                files = queries.setdefault(dep, [])
                if lockfile.path not in files:
                    files.append(lockfile.path)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(
            transport=self.transport, timeout=TIMEOUT, headers=headers
        ) as client:
            found = await _query(client, list(queries))
            ids = list(dict.fromkeys(i for vuln_ids in found.values() for i in vuln_ids))
            # A GHSA advisory carries a severity, a PYSEC copy of it often doesn't.
            ids.sort(key=lambda i: not i.startswith("GHSA-"))
            details = await _details(client, ids[:MAX_DETAILS])
        return ToolOutput(content=_report(lockfiles, queries, found, details))


# -- Finding and parsing lockfiles


def _kind(name: str) -> str | None:
    if name in FIXED_NAMES:
        return name
    return "requirements.txt" if REQUIREMENTS.match(name) else None


async def _lockfiles(path: str, ctx: ToolContext) -> list[Lockfile]:
    name = PurePosixPath(path).name
    if _kind(name):
        return [_parse(path, await _read(path, ctx))]
    folder = ctx.executor.search_path(path)
    paths = await _find(folder, ctx)
    lockfiles = []
    for found in paths[:MAX_FILES]:
        try:
            data = await ctx.executor.read_bytes(found)
        except OSError:
            continue
        lockfiles.append(_parse(found, data))
    if not lockfiles:
        known = ", ".join([*FIXED_NAMES, "requirements*.txt"])
        raise ToolError(f"No lockfiles found in {path}. Looked for {known}.")
    if len(paths) > MAX_FILES:
        lockfiles[-1].note += f" ({len(paths) - MAX_FILES} more lockfiles not read)"
    return lockfiles


async def _read(path: str, ctx: ToolContext) -> bytes:
    try:
        return await ctx.executor.read_bytes(path)
    except FileNotFoundError as exc:
        raise ToolError(f"There's no file at {path}.") from exc
    except OSError as exc:
        raise ToolError(f"Couldn't read {path}: {exc.strerror or exc}") from exc


async def _find(folder: str, ctx: ToolContext) -> list[str]:
    """Lockfiles in the folder and two levels below it, skipping installed packages."""
    argv = ["rg", "--files", "--no-require-git", "--path-separator", "/", "--max-depth", "3"]
    argv += skipped()
    for name in [*FIXED_NAMES, "requirements*.txt"]:
        argv += ["--glob", name]
    argv.append(folder)
    try:
        result = await ctx.executor.run(argv, timeout=30)
    except OSError:
        result = None
    if result is not None and result.exit_code in (0, 1):
        paths = [line.removeprefix("./") for line in result.output.splitlines() if line.strip()]
        paths = [p for p in paths if _kind(PurePosixPath(p).name)]
        # The folder's own lockfiles first, then the ones below it.
        return sorted(set(paths), key=lambda p: (p.count("/"), p))
    # Without ripgrep, the usual names in the folder itself.
    names = [*FIXED_NAMES, "requirements.txt", "requirements-dev.txt"]
    return [str(PurePosixPath(folder) / name) if folder != "." else name for name in names]


def _parse(path: str, data: bytes) -> Lockfile:
    kind = _kind(PurePosixPath(path).name) or ""
    text = data.decode("utf-8", "replace")
    parser = PARSERS[kind]
    try:
        deps, note = parser(text)
    except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError) as exc:
        raise ToolError(f"Couldn't parse {path}: {exc}") from exc
    return Lockfile(path, list(dict.fromkeys(deps)), note)


type Parsed = tuple[list[Dep], str]


def _toml_packages(text: str, ecosystem: str, keep: Callable[[dict[str, Any]], bool]) -> Parsed:
    data = tomllib.loads(text)
    deps = []
    for package in data.get("package") or []:
        name, version = package.get("name"), package.get("version")
        if isinstance(name, str) and isinstance(version, str) and keep(package):
            deps.append(Dep(ecosystem, name, version))
    return deps, ""


def _uv(text: str) -> Parsed:
    def keep(package: dict[str, Any]) -> bool:
        # The project itself and its local packages aren't on PyPI.
        source = package.get("source") or {}
        return not any(key in source for key in ("editable", "virtual", "path", "directory"))

    return _toml_packages(text, "PyPI", keep)


def _poetry(text: str) -> Parsed:
    def keep(package: dict[str, Any]) -> bool:
        source = package.get("source") or {}
        return source.get("type") not in ("directory", "file")

    return _toml_packages(text, "PyPI", keep)


def _cargo(text: str) -> Parsed:
    # The workspace's own crates have no source.
    return _toml_packages(text, "crates.io", lambda package: "source" in package)


PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*===?\s*([^\s;#\\,]+)")


def _requirements(text: str) -> Parsed:
    deps = []
    unpinned = 0
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = PIN.match(line)
        if match:
            deps.append(Dep("PyPI", match.group(1), match.group(2)))
        else:
            unpinned += 1
    if unpinned:
        lines = "line" if unpinned == 1 else "lines"
        return deps, f"{unpinned} unpinned {lines} skipped"
    return deps, ""


def _pipfile(text: str) -> Parsed:
    data = json.loads(text)
    deps = []
    for section in ("default", "develop"):
        for name, info in (data.get(section) or {}).items():
            version = info.get("version") if isinstance(info, dict) else None
            if isinstance(version, str) and version.startswith("=="):
                deps.append(Dep("PyPI", name, version.lstrip("=")))
    return deps, ""


def _npm_version(version: object) -> bool:
    return isinstance(version, str) and bool(re.match(r"\d", version))


def _package_lock(text: str) -> Parsed:
    data = json.loads(text)
    deps = []
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, info in packages.items():
            if "node_modules/" not in key or not isinstance(info, dict) or info.get("link"):
                continue
            name = info.get("name") or key.rsplit("node_modules/", 1)[1]
            if _npm_version(info.get("version")):
                deps.append(Dep("npm", str(name), info["version"]))
        return deps, ""

    def walk(tree: object) -> None:
        if not isinstance(tree, dict):
            return
        for name, info in tree.items():
            if isinstance(info, dict):
                if _npm_version(info.get("version")):
                    deps.append(Dep("npm", name, info["version"]))
                walk(info.get("dependencies"))

    walk(data.get("dependencies"))
    return deps, ""


LOCAL_PROTOCOL = re.compile(r"^(?:workspace|patch|link|portal|file|exec|git\+?\w*|github|https?):")


def _yarn_name(spec: str) -> str | None:
    """The package a yarn.lock entry's first spec names, or None for a local or patched one."""
    spec = spec.strip().strip('"').strip("'")
    at = spec.find("@", 1)
    if at < 0:
        return None
    name, rest = spec[:at], spec[at + 1 :]
    if LOCAL_PROTOCOL.match(rest):
        return None
    if rest.startswith("npm:"):
        aliased = rest[4:]
        inner = aliased.find("@", 1)
        if inner > 0:  # "alias@npm:real@^1.0.0"
            return aliased[:inner]
    return name


YARN_VERSION = re.compile(r"^\s+version:?\s+\"?([^\"\s]+)\"?\s*$")


def _yarn(text: str) -> Parsed:
    deps = []
    name: str | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            header = line.rstrip().rstrip(":")
            name = None if header == "__metadata" else _yarn_name(header.split(",")[0])
            continue
        match = YARN_VERSION.match(line)
        if match and name and _npm_version(match.group(1)):
            deps.append(Dep("npm", name, match.group(1)))
            name = None
    return deps, ""


PNPM_KEY = re.compile(r"^  (['\"]?)(/?[^\s'\"]+)\1:(?:\s.*)?$")
NPM_NAME = r"(@[^@/\s]+/[^@/\s]+|[^@/\s]+)"
PNPM_AT = re.compile(NPM_NAME + r"@(\d[^_(\s]*)")  # lockfile v6 and later: name@1.2.3
PNPM_SLASH = re.compile(NPM_NAME + r"/(\d[^_(/\s]*)")  # v5: /name/1.2.3_peers


def _pnpm(text: str) -> Parsed:
    deps = []
    section = ""
    for line in text.splitlines():
        if line and not line[0].isspace():
            section = line.split(":", 1)[0].strip()
            continue
        if section not in ("packages", "snapshots"):
            continue
        match = PNPM_KEY.match(line)
        if not match:
            continue
        key = match.group(2).lstrip("/")
        found = PNPM_AT.match(key) or PNPM_SLASH.match(key)
        if found:
            deps.append(Dep("npm", found.group(1), found.group(2)))
    return deps, ""


def _go_sum(text: str) -> Parsed:
    # go.sum lists every version the module graph mentions; the build uses the highest, and
    # a version with a hash of its whole source (not only its go.mod) is one Go downloaded.
    versions: dict[str, dict[str, bool]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        module, version = parts[0], parts[1]
        full = not version.endswith("/go.mod")
        version = version.removesuffix("/go.mod")
        seen = versions.setdefault(module, {})
        seen[version] = seen.get(version, False) or full
    deps = []
    for module, seen in versions.items():
        candidates = [v for v, full in seen.items() if full] or list(seen)
        deps.append(Dep("Go", module, max(candidates, key=version_key)))
    return deps, ""


GEM_SPEC = re.compile(r"^    ([^\s(]+) \(([^)]+)\)\s*$")


def _gemfile(text: str) -> Parsed:
    deps = []
    section = ""
    for line in text.splitlines():
        if line and not line[0].isspace():
            section = line.strip()
            continue
        match = GEM_SPEC.match(line)
        if section == "GEM" and match:
            # A platform gem's version ends with its platform: 1.13.10-x86_64-linux
            version = re.sub(r"-[a-z].*$", "", match.group(2))
            deps.append(Dep("RubyGems", match.group(1), version))
    return deps, ""


PARSERS: dict[str, Callable[[str], Parsed]] = {
    "uv.lock": _uv,
    "poetry.lock": _poetry,
    "Cargo.lock": _cargo,
    "requirements.txt": _requirements,
    "Pipfile.lock": _pipfile,
    "package-lock.json": _package_lock,
    "npm-shrinkwrap.json": _package_lock,
    "yarn.lock": _yarn,
    "pnpm-lock.yaml": _pnpm,
    "go.sum": _go_sum,
    "Gemfile.lock": _gemfile,
}


# -- Asking OSV.dev


async def _query(client: httpx.AsyncClient, deps: list[Dep]) -> dict[Dep, list[str]]:
    """The ids of the advisories affecting each dependency that has any."""
    found: dict[Dep, list[str]] = {}
    for start in range(0, len(deps), BATCH):
        chunk = deps[start : start + BATCH]
        body = {
            "queries": [
                {"package": {"name": d.name, "ecosystem": d.ecosystem}, "version": d.version}
                for d in chunk
            ]
        }
        try:
            reply = await client.post(QUERY_BATCH, json=body)
        except httpx.HTTPError as exc:
            raise ToolError(f"Couldn't reach OSV.dev: {exc or type(exc).__name__}") from exc
        if reply.status_code >= 400:
            raise ToolError(f"OSV.dev answered with HTTP {reply.status_code}: {reply.text[:200]}")
        try:
            results = reply.json().get("results") or []
        except ValueError as exc:
            raise ToolError("OSV.dev sent something that isn't JSON.") from exc
        for dep, result in zip(chunk, results, strict=False):
            ids = [str(v["id"]) for v in (result or {}).get("vulns") or [] if v.get("id")]
            if ids:
                found[dep] = ids
    return found


async def _details(client: httpx.AsyncClient, ids: list[str]) -> dict[str, dict[str, Any]]:
    limit = asyncio.Semaphore(PARALLEL)

    async def one(vuln_id: str) -> tuple[str, dict[str, Any] | None]:
        async with limit:
            try:
                reply = await client.get(VULN + vuln_id)
                if reply.status_code == 200:
                    data = reply.json()
                    return vuln_id, data if isinstance(data, dict) else None
            except (httpx.HTTPError, ValueError):
                pass
            return vuln_id, None

    pairs = await asyncio.gather(*(one(i) for i in ids))
    return {vuln_id: data for vuln_id, data in pairs if data is not None}


def _normal(ecosystem: str, name: str) -> str:
    if ecosystem == "PyPI":
        return re.sub(r"[-_.]+", "-", name).lower()
    return name.lower() if ecosystem in ("npm", "crates.io") else name


def _advisory(vuln_id: str, data: dict[str, Any] | None, dep: Dep) -> Advisory:
    if data is None:
        return Advisory(vuln_id, [vuln_id])
    aliases = [str(a) for a in data.get("aliases") or []]
    cves = [a for a in aliases if a.startswith("CVE-")]
    advisory = Advisory(vuln_id, [vuln_id, *cves], detailed=True)
    advisory.names += [a for a in aliases if a not in advisory.names]  # for merging copies
    text = str(data.get("summary") or "").strip() or str(data.get("details") or "").strip()
    advisory.summary = " ".join(text.split("\n\n")[0].split())[:MAX_SUMMARY]
    vectors = [s for s in data.get("severity") or [] if isinstance(s, dict)]
    labels = []
    database = data.get("database_specific")
    if isinstance(database, dict) and isinstance(database.get("severity"), str):
        labels.append(database["severity"].upper())
    wanted = _normal(dep.ecosystem, dep.name)
    for affected in data.get("affected") or []:
        package = affected.get("package") or {}
        if _normal(str(package.get("ecosystem", "")).split(":")[0], str(package.get("name"))) != (
            wanted
        ):
            continue
        vectors += [s for s in affected.get("severity") or [] if isinstance(s, dict)]
        for extra in ("database_specific", "ecosystem_specific"):
            more = affected.get(extra)
            if isinstance(more, dict) and isinstance(more.get("severity"), str):
                labels.append(more["severity"].upper())
        for ranged in affected.get("ranges") or []:
            if ranged.get("type") == "GIT":
                continue
            for event in ranged.get("events") or []:
                if "fixed" in event:
                    advisory.fixed.append(str(event["fixed"]))
                if "last_affected" in event:
                    advisory.last_affected.append(str(event["last_affected"]))
    scores = [s for s in (cvss3_score(str(v.get("score", ""))) for v in vectors) if s is not None]
    label = next((label for label in labels if label in LABEL_SCORES), "")
    if scores:
        score = max(scores)
        advisory.score = score
        advisory.severity = f"{label or _label(score)} {score:.1f}"
    elif label:
        advisory.score = LABEL_SCORES[label]
        advisory.severity = label
    return advisory


def _label(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW" if score > 0 else "NONE"


CVSS3 = {
    "AV": {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2},
    "AC": {"L": 0.77, "H": 0.44},
    "UI": {"N": 0.85, "R": 0.62},
    "CIA": {"H": 0.56, "L": 0.22, "N": 0.0},
}


def cvss3_score(vector: str) -> float | None:
    """The base score of a CVSS 3.x vector, or None for anything else (CVSS 4 included)."""
    if not vector.startswith("CVSS:3."):
        return None
    metrics = dict(part.split(":", 1) for part in vector.split("/")[1:] if ":" in part)
    try:
        changed = metrics["S"] == "C"
        privileges = {"N": 0.85, "L": 0.68 if changed else 0.62, "H": 0.5 if changed else 0.27}
        av, ac = CVSS3["AV"][metrics["AV"]], CVSS3["AC"][metrics["AC"]]
        pr, ui = privileges[metrics["PR"]], CVSS3["UI"][metrics["UI"]]
        c, i, a = (CVSS3["CIA"][metrics[key]] for key in ("C", "I", "A"))
    except KeyError:
        return None
    base = 1 - (1 - c) * (1 - i) * (1 - a)
    impact = 7.52 * (base - 0.029) - 3.25 * (base - 0.02) ** 15 if changed else 6.42 * base
    if impact <= 0:
        return 0.0
    exploitability = 8.22 * av * ac * pr * ui
    total = (impact + exploitability) * (1.08 if changed else 1.0)
    return _round_up(min(total, 10.0))


def _round_up(value: float) -> float:
    whole = round(value * 100_000)
    if whole % 10_000 == 0:
        return whole / 100_000
    return (math.floor(whole / 10_000) + 1) / 10.0


# -- The report


def _merged(advisories: list[Advisory]) -> list[Advisory]:
    """One entry per vulnerability: GHSA-, PYSEC- and CVE- copies of it are listed together."""
    groups: list[Advisory] = []
    for advisory in sorted(advisories, key=lambda a: (not a.detailed, -a.score, a.id)):
        same = next((g for g in groups if set(g.names) & set(advisory.names)), None)
        if same is None:
            groups.append(advisory)
            continue
        same.names += [n for n in advisory.names if n not in same.names]
        same.fixed += advisory.fixed
        same.last_affected += advisory.last_affected
        same.summary = same.summary or advisory.summary
        if advisory.score > same.score:
            same.score, same.severity = advisory.score, advisory.severity
    return sorted(groups, key=lambda a: (-a.score, a.id))


def _fix(advisory: Advisory, version: str) -> str:
    fixed = sorted(set(advisory.fixed), key=version_key)
    if fixed:
        newer = [v for v in fixed if version_key(v) > version_key(version)]
        return f"fixed in {newer[0] if newer else ', '.join(fixed)}"
    if advisory.last_affected:
        last = max(advisory.last_affected, key=version_key)
        return f"no fix released (last affected {last})"
    return "no fixed version listed" if advisory.detailed else ""


def _shown_names(advisory: Advisory) -> str:
    ids = [advisory.id] + [n for n in advisory.names[1:] if n.startswith(("CVE-", "GHSA-"))]
    return " / ".join(dict.fromkeys(ids))


def _report(
    lockfiles: list[Lockfile],
    queries: dict[Dep, list[str]],
    found: dict[Dep, list[str]],
    details: dict[str, dict[str, Any]],
) -> str:
    per_ecosystem: dict[str, int] = {}
    for dep in queries:
        per_ecosystem[dep.ecosystem] = per_ecosystem.get(dep.ecosystem, 0) + 1
    totals = ", ".join(f"{e} {n:,}" for e, n in sorted(per_ecosystem.items()))
    files = "lockfile" if len(lockfiles) == 1 else "lockfiles"
    lines = [
        f"Checked {len(queries):,} pinned packages ({totals or 'none'}) in {len(lockfiles)} "
        f"{files} against OSV.dev:"
    ]
    width = max(len(lf.path) for lf in lockfiles)
    for lockfile in lockfiles:
        counts: dict[str, int] = {}
        for dep in lockfile.deps:
            counts[dep.ecosystem] = counts.get(dep.ecosystem, 0) + 1
        what = ", ".join(f"{e} {n:,}" for e, n in counts.items()) or "no pinned packages"
        note = f" ({lockfile.note.strip()})" if lockfile.note.strip() else ""
        lines.append(f"  {lockfile.path:<{width}}  {what}{note}")

    if not found:
        today = date.today().isoformat()
        lines += ["", f"No known vulnerabilities in {len(queries):,} packages (OSV.dev, {today})."]
        return "\n".join(lines)

    entries = []
    for dep, ids in found.items():
        advisories = _merged([_advisory(i, details.get(i), dep) for i in ids])
        entries.append((max(a.score for a in advisories), dep, advisories))
    entries.sort(key=lambda e: (-e[0], e[1].ecosystem, e[1].name.lower()))
    count = sum(len(a) for _, _, a in entries)
    packages = "package" if len(entries) == 1 else "packages"
    lines += ["", f"{len(entries)} vulnerable {packages} ({count} advisories), most severe first:"]
    missing = 0
    for _, dep, advisories in entries[:MAX_PACKAGES]:
        lines += ["", f"{dep.name} {dep.version} ({dep.ecosystem}, {', '.join(queries[dep])})"]
        for advisory in advisories:
            if not advisory.detailed:
                missing += 1
            parts = [_shown_names(advisory)]
            if advisory.severity:
                parts.append(advisory.severity)
            head = "  ".join(parts)
            summary = f": {advisory.summary}" if advisory.summary else ""
            fix = _fix(advisory, dep.version)
            lines.append(f"  - {head}{summary}" + (f" ({fix})" if fix else ""))
    if len(entries) > MAX_PACKAGES:
        lines += ["", f"... and {len(entries) - MAX_PACKAGES} more vulnerable packages."]
    if missing:
        lines += [
            "",
            f"{missing} advisories weren't fetched in full; read one at "
            "https://osv.dev/vulnerability/<id>.",
        ]
    text = "\n".join(lines)
    if len(text) > MAX_OUTPUT:
        text = text[:MAX_OUTPUT].rsplit("\n", 1)[0]
        text += "\n[... cut here; audit one lockfile at a time to see the rest]"
    return text
