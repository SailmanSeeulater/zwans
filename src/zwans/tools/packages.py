"""The Packages tool: what a package's registry says about it now, not what a model remembers.

Models suggest versions, flags and APIs from their training, which can be a year or two
behind: a version that was latest then, an option since removed. This asks the registry
(PyPI, npm or crates.io) for the latest version and the recent ones with their dates, the
links, and, where the project is on GitHub, its latest release notes; and OSV.dev for known
vulnerabilities in the version asked about.

Like WebFetch, the policy judges a call as a network request to the registry's host.
"""

import re
from typing import Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

Ecosystem = Literal["pypi", "npm", "crates"]
HOSTS = {"pypi": "pypi.org", "npm": "registry.npmjs.org", "crates": "crates.io"}
OSV_NAMES = {"pypi": "PyPI", "npm": "npm", "crates": "crates.io"}
OSV = "https://api.osv.dev/v1/query"
USER_AGENT = "Zwans (a coding agent looking up a package for its user)"
TIMEOUT = 15.0
RECENT = 8  # versions listed
MAX_NOTES = 2_000  # characters of release notes
MAX_VULNS = 10


class PackagesInput(BaseModel):
    name: str = Field(min_length=1, description="The package's name, as you'd install it.")
    ecosystem: Ecosystem = Field(
        default="pypi", description="Where it's published: pypi, npm or crates (Rust)."
    )
    version: str | None = Field(
        default=None,
        description="A version to check for known vulnerabilities, as the one the project "
        "uses. Leave it out to check the latest.",
    )


class PackagesTool:
    name = "Packages"
    description = (
        "Look up a package on PyPI, npm or crates.io: its latest version and recent ones "
        "with dates, what it needs, its links, its latest release notes, and known "
        "vulnerabilities in a version. Use it before choosing a version or an API you "
        "remember, which may be out of date."
    )
    input_model = PackagesInput
    read_only = False  # it sends a request out, which the policy judges like a network command

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    def host(self, args: dict[str, Any]) -> str:
        ecosystem = args.get("ecosystem") or "pypi"
        return HOSTS.get(str(ecosystem), "")

    async def run(self, args: PackagesInput, ctx: ToolContext) -> ToolOutput:
        name = args.name.strip()
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(
            transport=self.transport, timeout=TIMEOUT, headers=headers, follow_redirects=True
        ) as client:
            look = {"pypi": _pypi, "npm": _npm, "crates": _crates}[args.ecosystem]
            found = await look(client, name)
            version = (args.version or "").strip() or found.latest
            lines = found.lines()
            lines.append("")
            lines.append(await _vulnerabilities(client, args.ecosystem, found.name, version))
            if found.github:
                notes = await _release_notes(client, found.github)
                if notes:
                    lines += ["", notes]
        return ToolOutput(content="\n".join(lines))


class Found:
    def __init__(self, name: str, where: str) -> None:
        self.name = name
        self.where = where
        self.latest = ""
        self.released = ""
        self.summary = ""
        self.needs = ""
        self.license = ""
        self.recent: list[tuple[str, str]] = []  # (version, date)
        self.links: dict[str, str] = {}
        self.warning = ""
        self.github = ""  # owner/repo

    def lines(self) -> list[str]:
        when = f", released {self.released}" if self.released else ""
        lines = [f"{self.name} on {self.where}: latest {self.latest}{when}"]
        if self.warning:
            lines.append(f"Warning: {self.warning}")
        if self.summary:
            lines.append(self.summary.strip())
        about = [part for part in (self.needs, self.license) if part]
        if about:
            lines.append(". ".join(about) + ".")
        # Newest first; pre-releases apart, so a run of them doesn't hide the stable ones.
        stable = [(v, d) for v, d in self.recent if not is_prerelease(v)]
        if stable:
            shown = [f"{v} ({d})" if d else v for v, d in stable[:RECENT]]
            lines.append("Recent versions: " + ", ".join(shown))
        newest = self.recent[0] if self.recent else None
        if newest and is_prerelease(newest[0]):
            when = f" ({newest[1]})" if newest[1] else ""
            lines.append(f"Newest pre-release: {newest[0]}{when}")
        for label, url in list(self.links.items())[:6]:
            lines.append(f"{label}: {url}")
        return lines


async def _get(client: httpx.AsyncClient, url: str, what: str) -> Any:
    try:
        reply = await client.get(url)
    except httpx.HTTPError as exc:
        raise ToolError(f"Couldn't reach {what}: {exc or type(exc).__name__}") from exc
    if reply.status_code == 404:
        raise ToolError(f"{what} has no package by that name.")
    if reply.status_code >= 400:
        raise ToolError(f"{what} answered with HTTP {reply.status_code}.")
    try:
        return reply.json()
    except ValueError as exc:
        raise ToolError(f"{what} sent something that isn't JSON.") from exc


async def _pypi(client: httpx.AsyncClient, name: str) -> Found:
    data = await _get(client, f"https://pypi.org/pypi/{quote(name)}/json", "PyPI")
    info = data.get("info") or {}
    found = Found(str(info.get("name") or name), "PyPI")
    found.latest = str(info.get("version") or "")
    found.summary = str(info.get("summary") or "")
    if info.get("requires_python"):
        found.needs = f"Requires Python {info['requires_python']}"
    license_name = info.get("license_expression") or info.get("license") or ""
    if isinstance(license_name, str) and 0 < len(license_name) < 60:
        found.license = f"License {license_name}"
    dated = []
    for version, files in (data.get("releases") or {}).items():
        if not files:
            continue
        times = sorted(str(f.get("upload_time") or "")[:10] for f in files)
        yanked = all(f.get("yanked") for f in files)
        dated.append((times[0], version + (" (yanked)" if yanked else "")))
    dated.sort(reverse=True)
    found.recent = [(version, date) for date, version in dated]
    found.released = next((d for d, v in dated if v == found.latest), "")
    if info.get("yanked"):
        found.warning = (
            f"{found.latest} was yanked: {info.get('yanked_reason') or 'no reason given'}"
        )
    urls = info.get("project_urls") or {}
    if isinstance(urls, dict):
        found.links = {str(k): str(v) for k, v in urls.items() if isinstance(v, str)}
    if not found.links and info.get("home_page"):
        found.links["Homepage"] = str(info["home_page"])
    found.github = _github(*found.links.values())
    return found


async def _npm(client: httpx.AsyncClient, name: str) -> Found:
    # The full document of a popular package runs to megabytes; these two are small.
    abbreviated = await _npm_versions(client, name)
    latest = (abbreviated.get("dist-tags") or {}).get("latest") or ""
    found = Found(name, "npm")
    found.latest = str(latest)
    versions = list((abbreviated.get("versions") or {}).keys())
    deprecated = (abbreviated.get("versions") or {}).get(latest, {}).get("deprecated")
    if deprecated:
        found.warning = f"{latest} is deprecated: {deprecated}"
    # The registry doesn't list versions in the order they came out, so by number.
    found.recent = [(v, "") for v in sorted(versions, key=version_key, reverse=True)]
    if latest:
        doc = await _get(client, f"https://registry.npmjs.org/{_npm_path(name)}/{latest}", "npm")
        found.summary = str(doc.get("description") or "")
        engines = doc.get("engines") or {}
        if isinstance(engines, dict) and engines.get("node"):
            found.needs = f"Requires Node {engines['node']}"
        if isinstance(doc.get("license"), str):
            found.license = f"License {doc['license']}"
        repo = doc.get("repository")
        repo_url = repo.get("url") if isinstance(repo, dict) else repo
        if isinstance(doc.get("homepage"), str):
            found.links["Homepage"] = doc["homepage"]
        if isinstance(repo_url, str):
            found.links["Repository"] = re.sub(r"^git\+|\.git$", "", repo_url)
        found.github = _github(*found.links.values())
    modified = abbreviated.get("modified")
    if isinstance(modified, str):
        found.released = f"package last changed {modified[:10]}"
    return found


async def _npm_versions(client: httpx.AsyncClient, name: str) -> Any:
    url = f"https://registry.npmjs.org/{_npm_path(name)}"
    try:
        reply = await client.get(url, headers={"Accept": "application/vnd.npm.install-v1+json"})
    except httpx.HTTPError as exc:
        raise ToolError(f"Couldn't reach npm: {exc or type(exc).__name__}") from exc
    if reply.status_code == 404:
        raise ToolError("npm has no package by that name.")
    if reply.status_code >= 400:
        raise ToolError(f"npm answered with HTTP {reply.status_code}.")
    return reply.json()


def _npm_path(name: str) -> str:
    return quote(name, safe="@")  # a scoped package's slash is encoded


async def _crates(client: httpx.AsyncClient, name: str) -> Found:
    data = await _get(client, f"https://crates.io/api/v1/crates/{quote(name)}", "crates.io")
    crate = data.get("crate") or {}
    found = Found(str(crate.get("name") or name), "crates.io")
    found.latest = str(crate.get("max_stable_version") or crate.get("max_version") or "")
    found.summary = str(crate.get("description") or "")
    versions = data.get("versions") or []
    found.recent = [
        (
            str(v.get("num")) + (" (yanked)" if v.get("yanked") else ""),
            str(v.get("created_at"))[:10],
        )
        for v in versions
    ]
    found.released = next((d for v, d in found.recent if v == found.latest), "")
    first = versions[0] if versions else {}
    if first.get("rust_version"):
        found.needs = f"Requires Rust {first['rust_version']}"
    if first.get("license"):
        found.license = f"License {first['license']}"
    for label, key in (
        ("Homepage", "homepage"),
        ("Repository", "repository"),
        ("Docs", "documentation"),
    ):
        if crate.get(key):
            found.links[label] = str(crate[key])
    found.github = _github(*found.links.values())
    return found


PRERELEASE = re.compile(
    r"\d[-.]?(?:a|b|c|rc|alpha|beta|pre|preview|dev|canary|next|nightly)\d*", re.I
)


def is_prerelease(version: str) -> bool:
    return "-" in version or bool(PRERELEASE.search(version))


def version_key(version: str) -> tuple[tuple[int, ...], int]:
    """Orders versions by their numbers, a pre-release before its release."""
    numbers = tuple(int(n) for n in re.findall(r"\d+", re.split(r"[-+]", version)[0]))
    return numbers, 0 if is_prerelease(version) else 1


def _github(*urls: str) -> str:
    for url in urls:
        match = re.match(r"https?://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?]|$)", url)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return ""


async def _vulnerabilities(
    client: httpx.AsyncClient, ecosystem: Ecosystem, name: str, version: str
) -> str:
    query = {"package": {"name": name, "ecosystem": OSV_NAMES[ecosystem]}, "version": version}
    try:
        reply = await client.post(OSV, json=query)
        reply.raise_for_status()
        vulns = reply.json().get("vulns") or []
    except (httpx.HTTPError, ValueError) as exc:
        why = str(exc) or type(exc).__name__
        return f"Known vulnerabilities in {version}: couldn't ask OSV.dev ({why})."
    if not vulns:
        return f"Known vulnerabilities in {version}: none on OSV.dev."
    lines = [f"Known vulnerabilities in {version} ({len(vulns)} on OSV.dev):"]
    for vuln in vulns[:MAX_VULNS]:
        names = [
            vuln.get("id", "?"),
            *[a for a in vuln.get("aliases") or [] if a.startswith("CVE-")],
        ]
        summary = str(vuln.get("summary") or vuln.get("details") or "").strip().split("\n")[0][:160]
        fixed = sorted(
            {
                str(event["fixed"])
                for affected in vuln.get("affected") or []
                for ranged in affected.get("ranges") or []
                for event in ranged.get("events") or []
                if "fixed" in event
            }
        )
        fix = f" Fixed in {', '.join(fixed)}." if fixed else ""
        lines.append(f"- {' / '.join(dict.fromkeys(names))}: {summary}{fix}")
    if len(vulns) > MAX_VULNS:
        lines.append(f"- and {len(vulns) - MAX_VULNS} more")
    return "\n".join(lines)


async def _release_notes(client: httpx.AsyncClient, repo: str) -> str:
    url = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    try:
        reply = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        releases = reply.json() if reply.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return ""
    releases = [r for r in releases if isinstance(r, dict) and not r.get("draft")]
    if not releases:
        return ""
    latest = releases[0]
    body = str(latest.get("body") or "").strip()
    if len(body) > MAX_NOTES:
        body = body[:MAX_NOTES].rsplit("\n", 1)[0] + "\n[...]"
    tags = ", ".join(
        f"{r.get('tag_name')} ({str(r.get('published_at') or '')[:10]})" for r in releases
    )
    head = f"Releases on GitHub ({repo}): {tags}"
    title = latest.get("name") or latest.get("tag_name")
    return f"{head}\nNotes for {title}:\n{body or '(none written)'}"
