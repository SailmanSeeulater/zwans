"""Zip and tar archives: Read lists what is in one, and the Archive tool unpacks it.

An archive is binary, so Read used to refuse it, and unpacking it meant `unzip` or `tar`
through Bash, which writes wherever the archive says: an entry named `../../.bashrc`, an
absolute path or a symbolic link pointing out of the folder all go where they point, and a
small file can expand to fill the disk. Here Read shows the list of members (path, size,
date), and Archive unpacks in memory and writes each file through the executor, which keeps
it inside the workspace. Entries that would leave the destination folder, links and device
files are skipped and reported, existing files are kept unless asked otherwise, and an
archive that would unpack to more than 10,000 files or 1 GB is refused, judging both by the
sizes it declares and by the bytes that actually come out.

The kind of archive is told from its first bytes, not its name, so a `.jar`, `.whl` or
`.docx` (all zips) and a tarball without an extension are recognised too.
"""

import bz2
import fnmatch
import functools
import gzip
import io
import lzma
import os
import stat
import tarfile
import time
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Literal, NoReturn

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_FILES = 10_000  # files one extraction may write
MAX_TOTAL_BYTES = 1_000_000_000  # uncompressed bytes one extraction may write
MAX_LISTED = 300  # members Read lists
MAX_SCANNED = 200_000  # members Read looks at to count them
MAX_REPORTED = 20  # skipped entries named in a report
CHUNK = 1 << 20

Kind = Literal["zip", "tar", "gzip", "bzip2", "xz"]
COMPRESSED_NAMES = {"gzip": "gzip", "bzip2": "bzip2", "xz": "xz"}
EXTENSIONS = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tbz2",
    ".tbz",
    ".txz",
    ".tar",
    ".zip",
    ".jar",
    ".whl",
)


def archive_kind(data: bytes, name: str = "") -> Kind | None:
    """What kind of archive the bytes are, told from their first bytes."""
    if data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:3] == b"BZh":
        return "bzip2"
    if data[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if data[257:262] == b"ustar":
        return "tar"
    if name.lower().endswith(".tar") and len(data) >= 512:
        return "tar"  # an old tar with no magic: tried, and refused if it isn't one
    return None


def is_archive(data: bytes, name: str = "") -> bool:
    return archive_kind(data, name) is not None


@dataclass
class Member:
    name: str  # as the archive spells it
    kind: Literal["file", "dir", "symlink", "hardlink", "special"]
    size: int  # declared, uncompressed
    modified: float | None  # seconds since the epoch, in local time for a zip
    mode: int = 0
    target: str = ""  # a link's
    encrypted: bool = False
    open: Callable[[], IO[bytes]] | None = None  # the file's contents, while iterating


def _zip_members(data: bytes) -> Iterator[Member]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ToolError(f"This isn't a zip archive that can be read: {exc}") from exc
    with archive:
        for info in archive.infolist():
            mode = info.external_attr >> 16
            kind: Literal["file", "dir", "symlink", "hardlink", "special"] = "file"
            target = ""
            if info.is_dir():
                kind = "dir"
            elif stat.S_ISLNK(mode):
                kind = "symlink"
                if info.file_size < 4096 and not info.flag_bits & 0x1:
                    try:
                        target = archive.read(info).decode("utf-8", "replace")
                    except (zipfile.BadZipFile, OSError, ValueError):
                        target = "?"
            elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
                kind = "special"
            try:
                modified = time.mktime((*info.date_time, 0, 0, -1))
            except (OverflowError, ValueError):
                modified = None
            yield Member(
                name=info.filename,
                kind=kind,
                size=info.file_size,
                modified=modified,
                mode=mode,
                target=target,
                encrypted=bool(info.flag_bits & 0x1),
                open=functools.partial(archive.open, info),
            )


def _tar_members(data: bytes) -> Iterator[Member]:
    # Streamed, so a member's contents are decompressed only as far as they're read, and a
    # member that isn't read is skipped over without being kept.
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r|*")  # noqa: SIM115
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ToolError(f"This isn't a tar archive that can be read: {exc}") from exc
    with archive:
        try:
            for info in archive:
                kind: Literal["file", "dir", "symlink", "hardlink", "special"]
                if info.isreg():
                    kind = "file"
                elif info.isdir():
                    kind = "dir"
                elif info.issym():
                    kind = "symlink"
                elif info.islnk():
                    kind = "hardlink"
                else:
                    kind = "special"
                opener = None
                if kind == "file":
                    opener = _tar_opener(archive, info)
                yield Member(
                    name=info.name,
                    kind=kind,
                    size=info.size,
                    modified=float(info.mtime),
                    mode=info.mode,
                    target=info.linkname,
                    open=opener,
                )
        except (tarfile.TarError, OSError, EOFError, zipfile.BadZipFile) as exc:
            raise ToolError(f"The archive is damaged or cut short: {exc}") from exc


def _tar_opener(archive: tarfile.TarFile, info: tarfile.TarInfo) -> Callable[[], IO[bytes]]:
    def opener() -> IO[bytes]:
        member = archive.extractfile(info)
        if member is None:
            raise ToolError(f"{info.name} has no contents to read.")
        return member

    return opener


def members(data: bytes, name: str) -> Iterator[Member]:
    kind = archive_kind(data, name)
    if kind == "zip":
        return _zip_members(data)
    if kind is None:
        raise ToolError(f"{name} isn't a zip or tar archive.")
    return _tar_members(data)


def _is_tar(data: bytes, kind: Kind) -> bool:
    """Whether compressed bytes hold a tar archive, rather than one compressed file."""
    if kind == "zip":
        return True
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r|*") as archive:
            archive.next()
    except (tarfile.TarError, OSError, EOFError):
        return False
    return True


# -- listing, for Read


def read_archive(data: bytes, name: str) -> ToolOutput:
    """What Read shows for an archive: its members, with totals."""
    kind = archive_kind(data, name)
    assert kind is not None
    if not _is_tar(data, kind):
        if kind == "tar":
            raise ToolError(f"{name} looks like a binary file, so it isn't shown.")
        return _compressed_file(data, name, kind)
    rows: list[str] = []
    files = folders = links = total = scanned = 0
    for member in members(data, name):
        scanned += 1
        if scanned > MAX_SCANNED:
            break
        if member.kind == "file":
            files += 1
            total += member.size
        elif member.kind == "dir":
            folders += 1
        else:
            links += 1
        if len(rows) < MAX_LISTED:
            rows.append(_row(member))
    labels = {"zip": "zip archive", "tar": "tar archive"}
    label = labels.get(kind) or f"{COMPRESSED_NAMES[kind]}-compressed tar archive"
    summary = (
        f"{name}: a {label} of {_count(files, 'file')} ({_size(total)} uncompressed, "
        f"{_size(len(data))} on disk)"
    )
    extra = []
    if folders:
        extra.append(_count(folders, "folder"))
    if links:
        extra.append(f"{_count(links, 'link')} or special file{'s' if links != 1 else ''}")
    summary += (", " + ", ".join(extra) if extra else "") + "."
    lines = [summary, "", f"{'Size':>13}  {'Modified':<16}  Path", *rows]
    if scanned > MAX_SCANNED:
        lines.append(f"(Stopped counting after {MAX_SCANNED:,} entries.)")
    elif scanned > len(rows):
        lines.append(
            f"(Showing the first {len(rows)} of {scanned:,} entries. Archive with `only` "
            "extracts just the ones matching a pattern.)"
        )
    lines.append("(Unpack it with the Archive tool.)")
    return ToolOutput(content="\n".join(lines))


def _compressed_file(data: bytes, name: str, kind: Kind) -> ToolOutput:
    """A single compressed file, as `app.log.gz`: its text, when it is text and not huge."""
    label = COMPRESSED_NAMES[kind]
    try:
        with _open_compressed(data, kind) as stream:
            inner = stream.read(MAX_LISTED * 1000 + 1)
    except (OSError, EOFError, lzma.LZMAError) as exc:
        raise ToolError(f"{name} is {label}-compressed but can't be decompressed: {exc}") from exc
    if b"\x00" in inner[:8192]:
        return ToolOutput(content=f"{name}: {label}-compressed binary data, not an archive.")
    text = inner[: MAX_LISTED * 1000].decode("utf-8", "replace")
    note = f"{name}: {label}-compressed text, shown decompressed"
    if len(inner) > MAX_LISTED * 1000:
        note += f" (the first {_size(MAX_LISTED * 1000)} of it)"
    return ToolOutput(content=f"{note}.\n\n{text}")


def _open_compressed(data: bytes, kind: Kind) -> io.BufferedIOBase:
    buffer = io.BytesIO(data)
    if kind == "gzip":
        return gzip.GzipFile(fileobj=buffer)
    if kind == "bzip2":
        return bz2.BZ2File(buffer)
    return lzma.LZMAFile(buffer)


def _row(member: Member) -> str:
    when = ""
    if member.modified is not None and member.modified > 0:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(member.modified))
    size = f"{member.size:,}" if member.kind == "file" else ""
    path = member.name
    if member.kind == "dir" and not path.endswith("/"):
        path += "/"
    elif member.kind in ("symlink", "hardlink"):
        path += f" -> {member.target}"
    elif member.kind == "special":
        path += " (device or pipe)"
    return f"{size:>13}  {when:<16}  {path}"


# -- extracting


class ArchiveInput(BaseModel):
    path: str = Field(description="The archive (zip, tar, tar.gz, tar.bz2 or tar.xz).")
    to: str = Field(
        default="",
        description="The folder to unpack into, relative to the workspace root. Leave it empty "
        "for a folder next to the archive named after it (data.tar.gz unpacks into data/).",
    )
    only: list[str] = Field(
        default=[],
        description='Glob patterns of members to unpack, as ["src/*", "*.json"]; a folder\'s '
        "name unpacks everything in it. Leave it empty for all of them.",
    )
    overwrite: bool = Field(
        default=False, description="Replace files that already exist. Off by default."
    )


class ArchiveTool:
    name = "Archive"
    description = (
        "Unpack a zip or tar archive (also .tar.gz, .tgz, .tar.bz2, .tar.xz) into a folder in "
        "the workspace. Entries that would land outside that folder, links and device files "
        "are skipped and listed, existing files are kept unless overwrite is set, and an "
        "archive that would unpack to more than 10,000 files or 1 GB is refused. Use only to "
        "unpack some members. To see what's inside first, Read the archive."
    )
    input_model = ArchiveInput
    read_only = False

    def edited_paths(self, args: dict[str, Any]) -> list[str]:
        """Unpacking writes into the destination, so it's judged like writing there."""
        to = args.get("to")
        if isinstance(to, str) and to.strip():
            return [to.strip()]
        path = args.get("path")
        return [default_destination(path)] if isinstance(path, str) and path else []

    async def run(self, args: ArchiveInput, ctx: ToolContext) -> ToolOutput:
        data = await ctx.executor.read_bytes(args.path)
        kind = archive_kind(data, args.path)
        if kind is None or not _is_tar(data, kind):
            raise ToolError(
                f"{args.path} isn't a zip or tar archive. A single compressed file (as "
                "file.gz) can be unpacked with gunzip, bunzip2 or unxz through Bash."
            )
        to = args.to.strip() or default_destination(args.path)
        try:
            destination = ctx.executor.relative(to)
        except OSError as exc:
            raise ToolError(f"{to} is outside the workspace.") from exc
        root = Path(getattr(ctx.executor, "root"))  # noqa: B009 (not on the Executor protocol)
        plan = _plan(data, args, destination, root)
        written, wrote_bytes = await _extract(data, args.path, plan, destination, root, ctx)
        return ToolOutput(content=_report(args.path, destination, plan, written, wrote_bytes))


def default_destination(path: str) -> str:
    """The folder next to the archive named after it, without its extension."""
    pure = PurePosixPath(path.replace("\\", "/"))
    name = pure.name
    lower = name.lower()
    for extension in EXTENSIONS:
        if lower.endswith(extension) and len(name) > len(extension):
            stem = name[: -len(extension)]
            break
    else:
        stem = name.rsplit(".", 1)[0] if "." in name.lstrip(".") else name + "-extracted"
    return str(pure.parent / stem) if str(pure.parent) not in ("", ".") else stem


def safe_path(name: str) -> str | None:
    """The member's path inside the destination, or None when it would leave it: an absolute
    path, a drive, or a `..` component."""
    name = name.replace("\\", "/")
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return None
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _wanted(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        pattern = pattern.strip().removeprefix("./")
        bare = pattern.rstrip("/")
        if fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path, bare):
            return True
        if bare and (path.startswith(bare + "/") or fnmatch.fnmatchcase(path, bare + "/*")):
            return True
    return False


@dataclass
class Plan:
    paths: dict[str, str]  # member name -> where it's written, for the files to write
    folders: list[str]  # empty folders to make
    existing: list[str]
    unsafe: list[str]
    links: list[str]
    blocked: list[str]  # writing there would go through a link
    junk: int = 0  # macOS metadata files (._name, __MACOSX/) left out


def _plan(data: bytes, args: ArchiveInput, destination: str, root: Path) -> Plan:
    plan = Plan({}, [], [], [], [], [])
    entries: list[tuple[Member, str]] = []
    for member in members(data, args.path):
        path = safe_path(member.name)
        if path is None:
            if member.name not in ("", ".", "./"):  # the archive's own folder is harmless
                plan.unsafe.append(member.name)
            continue
        if _is_junk(path):
            plan.junk += 1
            continue
        if _wanted(path, args.only):
            entries.append((member, path))
            if len(entries) > MAX_FILES * 2:  # folders and links count too, for memory
                _too_many(args.path)
    # An archive whose entries all sit in a folder named like the destination, as
    # tools.tar.gz holding tools/, unpacks next to itself rather than into tools/tools/.
    name = PurePosixPath(destination).name
    parent = str(PurePosixPath(destination).parent)
    base = destination
    if (
        not args.to.strip()
        and entries
        and all(path == name or path.startswith(name + "/") for _, path in entries)
    ):
        base = "" if parent == "." else parent
    count = total = 0
    seen: set[str] = set()
    for member, path in entries:
        if member.kind in ("symlink", "hardlink"):
            plan.links.append(f"{member.name} -> {member.target} ({member.kind})")
            continue
        if member.kind == "special":
            plan.links.append(f"{member.name} (device or pipe)")
            continue
        if member.encrypted:
            raise ToolError(f"{member.name} is encrypted, and Archive can't unpack it.")
        target = f"{base}/{path}" if base not in ("", ".") else path
        if member.kind == "dir":
            plan.folders.append(target)
            continue
        if path in seen:
            continue  # a later copy of the same name: the first is kept
        seen.add(path)
        count += 1
        total += member.size
        if count > MAX_FILES:
            _too_many(args.path)
        if total > MAX_TOTAL_BYTES:
            raise ToolError(
                f"{args.path} would unpack to more than {_size(MAX_TOTAL_BYTES)}, which is "
                "more than Archive unpacks at once (it may be a zip bomb). Use only to "
                "unpack part of it."
            )
        lexical = root / target
        if _through_link(root, target):
            plan.blocked.append(target)
        elif (lexical.exists() or lexical.is_symlink()) and not args.overwrite:
            plan.existing.append(target)
        else:
            plan.paths[member.name] = target
    return plan


def _too_many(name: str) -> NoReturn:
    raise ToolError(
        f"{name} holds more than {MAX_FILES:,} files, which is more than Archive unpacks at "
        "once. Use only to unpack part of it."
    )


def _is_junk(path: str) -> bool:
    parts = path.split("/")
    return "__MACOSX" in parts or parts[-1].startswith("._") or parts[-1] == ".DS_Store"


def _through_link(root: Path, target: str) -> bool:
    """Whether writing there would follow a symbolic link: the target or a folder above it."""
    current = root
    for part in PurePosixPath(target).parts:
        current = current / part
        if current.is_symlink():
            return True
        if not current.exists():
            return False
    return False


async def _extract(
    data: bytes, name: str, plan: Plan, destination: str, root: Path, ctx: ToolContext
) -> tuple[list[str], int]:
    written: list[str] = []
    done: set[str] = set()
    budget = MAX_TOTAL_BYTES
    for member in members(data, name):
        target = plan.paths.get(member.name)
        if target is None or member.kind != "file" or member.open is None:
            continue
        if target in done:
            continue
        try:
            with member.open() as stream:
                chunks = []
                size = 0
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > budget:
                        raise ToolError(
                            f"{name} unpacked to more than its declared sizes and passed "
                            f"{_size(MAX_TOTAL_BYTES)} at {member.name}, so Archive stopped "
                            f"(it may be a zip bomb). {len(written)} files were written "
                            f"before that, in {destination}."
                        )
                    chunks.append(chunk)
        except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError, lzma.LZMAError) as exc:
            raise ToolError(
                f"{member.name} couldn't be read from {name}: {exc}. {len(written)} files "
                f"were written before that, in {destination}."
            ) from exc
        budget -= size
        try:
            await ctx.executor.write_bytes(target, b"".join(chunks))
        except PermissionError:
            plan.blocked.append(target)
            continue
        except (IsADirectoryError, NotADirectoryError, FileExistsError):
            plan.blocked.append(target)
            continue
        if member.mode & 0o111:
            try:
                file = root / target
                file.chmod(file.stat().st_mode | (member.mode & 0o111))
            except OSError:
                pass
        written.append(target)
        done.add(target)
    for folder in plan.folders:
        try:
            ctx.executor.relative(folder)
            if not _through_link(root, folder):
                os.makedirs(root / folder, exist_ok=True)
        except OSError:
            continue
    return written, MAX_TOTAL_BYTES - budget


def _report(name: str, destination: str, plan: Plan, written: list[str], size: int) -> str:
    where = destination.rstrip("/") + "/" if destination not in ("", ".") else "the workspace root"
    lines = [f"Unpacked {_count(len(written), 'file')} ({_size(size)}) from {name} into {where}."]
    if written or plan.folders:
        lines.append("Top level: " + _top_level(written, plan.folders, destination))
    if plan.junk:
        lines.append(
            f"Left out {_count(plan.junk, 'macOS metadata file')} (._ files, __MACOSX, .DS_Store)."
        )
    if plan.existing:
        lines.append(
            f"Kept {_count(len(plan.existing), 'file')} that already existed (overwrite=true "
            "replaces them):"
        )
        lines += _listed(plan.existing)
    if plan.unsafe:
        lines.append(
            f"Skipped {_count(len(plan.unsafe), 'entry', 'entries')} whose path would leave the "
            "destination (absolute, or with ..):"
        )
        lines += _listed(plan.unsafe)
    if plan.links:
        lines.append(f"Skipped {_count(len(plan.links), 'link')} and special files:")
        lines += _listed(plan.links)
    if plan.blocked:
        lines.append(
            f"Skipped {_count(len(plan.blocked), 'file')} whose place is taken by a folder or "
            "reached through a link, or is outside the workspace:"
        )
        lines += _listed(plan.blocked)
    return "\n".join(lines)


def _top_level(written: list[str], folders: list[str], destination: str) -> str:
    prefix = destination.rstrip("/") + "/" if destination not in ("", ".") else ""
    counts: dict[str, int] = {}
    for path in [*written, *(folder + "/" for folder in folders)]:
        inner = path.removeprefix(prefix)
        if inner.strip("/") == "" or not path.startswith(prefix):
            continue  # the destination folder itself
        head, _, rest = inner.partition("/")
        key = head + ("/" if rest or inner.endswith("/") else "")
        counts[key] = counts.get(key, 0) + (1 if rest and not inner.endswith("/") else 0)
    shown = []
    for key in sorted(counts)[:30]:
        if key.endswith("/"):
            shown.append(f"{key} ({_count(counts[key], 'file')})" if counts[key] else key)
        else:
            shown.append(key)
    if len(counts) > 30:
        shown.append(f"and {len(counts) - 30} more")
    return ", ".join(shown)


def _listed(items: list[str]) -> list[str]:
    lines = [f"  {item}" for item in items[:MAX_REPORTED]]
    if len(items) > MAX_REPORTED:
        lines.append(f"  (and {len(items) - MAX_REPORTED} more)")
    return lines


def _count(number: int, noun: str, plural: str = "") -> str:
    return f"{number:,} {noun if number == 1 else (plural or noun + 's')}"


def _size(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return f"{size:,} bytes" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{value:.1f} GB"
