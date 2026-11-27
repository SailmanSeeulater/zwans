"""Archives in Read and the Archive tool, Cron, OpenAPI and Imports."""

import asyncio
import gzip
import io
import json
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from zwans.tools import archives
from zwans.tools.archives import ArchiveInput, ArchiveTool, default_destination, safe_path
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.cron import CronInput, CronTool, explain, parse
from zwans.tools.imports import (
    ImportsInput,
    ImportsTool,
    parse_jsonc,
    strip_comments,
    strongly_connected,
)
from zwans.tools.openapi import OpenAPIInput, OpenAPITool
from zwans.tools.read import ReadInput, ReadTool

needs_rg = pytest.mark.skipif(shutil.which("rg") is None, reason="needs ripgrep")


def run(tool: Any, args: Any, ctx: ToolContext) -> ToolOutput:
    output: ToolOutput = asyncio.run(tool.run(args, ctx))
    return output


# -- archives


def make_zip(entries: dict[str, bytes], links: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2024, 5, 1, 12, 30, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name, date_time=(2024, 5, 1, 12, 30, 0))
            info.external_attr = 0o120777 << 16
            archive.writestr(info, target)
    return buffer.getvalue()


def make_tar(entries: dict[str, bytes], links: dict[str, str], mode: str = "w:gz") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:  # type: ignore[call-overload]
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 1_714_566_600
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            archive.addfile(info, io.BytesIO(data))
        for name, target in links.items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return buffer.getvalue()


def test_read_lists_a_zip_found_by_its_bytes_not_its_name(tmp_path: Path, ctx: ToolContext) -> None:
    data = make_zip({"src/main.py": b"print('hi')\n" * 100, "README.md": b"# Demo\n"})
    (tmp_path / "bundle.bin").write_bytes(data)

    output = run(ReadTool(), ReadInput(path="bundle.bin"), ctx)
    lines = output.content.splitlines()
    assert lines[0].startswith("bundle.bin: a zip archive of 2 files (1.2 KB uncompressed")
    assert any(line.endswith("2024-05-01 12:30  src/main.py") for line in lines)
    assert any("1,200" in line and "src/main.py" in line for line in lines)
    assert lines[-1] == "(Unpack it with the Archive tool.)"


def test_read_lists_a_tarball_with_its_links_and_cuts_a_long_list(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = {f"pkg/file{n}.txt": b"x" * n for n in range(5)}
    (tmp_path / "pkg.tgz").write_bytes(make_tar(files, {"pkg/link": "/etc/passwd"}))
    monkeypatch.setattr(archives, "MAX_LISTED", 3)

    output = run(ReadTool(), ReadInput(path="pkg.tgz"), ctx)
    assert output.content.startswith("pkg.tgz: a gzip-compressed tar archive of 5 files (10 bytes")
    assert "1 link or special file." in output.content.splitlines()[0]
    assert "(Showing the first 3 of 6 entries." in output.content

    monkeypatch.setattr(archives, "MAX_LISTED", 300)
    full = run(ReadTool(), ReadInput(path="pkg.tgz"), ctx)
    assert "pkg/link -> /etc/passwd" in full.content


def test_read_shows_a_single_gzipped_text_file_decompressed(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "app.log.gz").write_bytes(gzip.compress(b"started\nready\n"))
    output = run(ReadTool(), ReadInput(path="app.log.gz"), ctx)
    assert (
        output.content
        == "app.log.gz: gzip-compressed text, shown decompressed.\n\nstarted\nready\n"
    )


def test_archive_unpacks_a_zip_and_skips_entries_that_would_leave_the_folder(
    tmp_path: Path, ctx: ToolContext
) -> None:
    data = make_zip(
        {
            "data/a.txt": b"alpha",
            "data/sub/b.txt": b"beta",
            "top.txt": b"top",
            "../evil.txt": b"gotcha",
            "/etc/evil.txt": b"gotcha",
            "data/../../evil2.txt": b"gotcha",
        },
        links={"data/link": "../../outside"},
    )
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "bundle.zip").write_bytes(data)

    output = run(ArchiveTool(), ArchiveInput(path="files/bundle.zip"), ctx)
    out = tmp_path / "files" / "bundle"
    assert (out / "data" / "a.txt").read_bytes() == b"alpha"
    assert (out / "data" / "sub" / "b.txt").read_bytes() == b"beta"
    assert (out / "top.txt").read_bytes() == b"top"
    assert not (tmp_path / "files" / "evil.txt").exists()
    assert not (tmp_path / "evil2.txt").exists()
    assert not (out / "data" / "link").exists()
    lines = output.content.splitlines()
    assert lines[0] == "Unpacked 3 files (12 bytes) from files/bundle.zip into files/bundle/."
    assert lines[1] == "Top level: data/ (2 files), top.txt"
    assert (
        "Skipped 3 entries whose path would leave the destination (absolute, or with ..):" in lines
    )
    assert "  ../evil.txt" in lines and "  /etc/evil.txt" in lines
    assert "  data/link -> ../../outside (symlink)" in lines


def test_archive_skips_a_symlink_in_a_tar_and_keeps_the_executable_bit(
    tmp_path: Path, ctx: ToolContext
) -> None:
    data = make_tar({"tool/run.sh": b"#!/bin/sh\necho hi\n"}, {"tool/passwd": "/etc/passwd"})
    (tmp_path / "tool.tar.gz").write_bytes(data)

    output = run(ArchiveTool(), ArchiveInput(path="tool.tar.gz", to="unpacked"), ctx)
    script = tmp_path / "unpacked" / "tool" / "run.sh"
    assert script.read_bytes().startswith(b"#!/bin/sh")
    assert sys.platform == "win32" or script.stat().st_mode & 0o111  # Windows has no such bit
    assert not (tmp_path / "unpacked" / "tool" / "passwd").is_symlink()
    assert "Skipped 1 link and special files:\n  tool/passwd -> /etc/passwd (symlink)" in (
        output.content
    )


def test_archive_holding_one_folder_of_its_name_unpacks_beside_itself(
    tmp_path: Path, ctx: ToolContext
) -> None:
    files = {"tools/a.py": b"a", "tools/sub/b.py": b"b", "._tools": b"mac", "tools/._a.py": b"m"}
    (tmp_path / "tools.tar.gz").write_bytes(make_tar(files, {}))

    output = run(ArchiveTool(), ArchiveInput(path="tools.tar.gz"), ctx)
    assert (tmp_path / "tools" / "sub" / "b.py").read_bytes() == b"b"
    assert not (tmp_path / "tools" / "tools").exists()
    assert not (tmp_path / "._tools").exists()
    assert output.content.splitlines() == [
        "Unpacked 2 files (2 bytes) from tools.tar.gz into tools/.",
        "Top level: a.py, sub/ (1 file)",
        "Left out 2 macOS metadata files (._ files, __MACOSX, .DS_Store).",
    ]


def test_archive_keeps_existing_files_unless_asked_to_overwrite(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "a.zip").write_bytes(make_zip({"keep.txt": b"new", "fresh.txt": b"fresh"}))
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "keep.txt").write_text("old")

    first = run(ArchiveTool(), ArchiveInput(path="a.zip"), ctx)
    assert (tmp_path / "a" / "keep.txt").read_text() == "old"
    assert (tmp_path / "a" / "fresh.txt").read_text() == "fresh"
    assert "Kept 1 file that already existed (overwrite=true replaces them):\n  a/keep.txt" in (
        first.content
    )

    second = run(ArchiveTool(), ArchiveInput(path="a.zip", overwrite=True), ctx)
    assert (tmp_path / "a" / "keep.txt").read_text() == "new"
    assert second.content.startswith("Unpacked 2 files")


def test_archive_unpacks_only_the_members_asked_for(tmp_path: Path, ctx: ToolContext) -> None:
    data = make_zip({"src/a.py": b"a", "src/deep/b.py": b"b", "docs/x.md": b"x", "c.json": b"{}"})
    (tmp_path / "p.zip").write_bytes(data)

    output = run(ArchiveTool(), ArchiveInput(path="p.zip", only=["src", "*.json"]), ctx)
    assert output.content.startswith("Unpacked 3 files")
    assert (tmp_path / "p" / "src" / "deep" / "b.py").exists()
    assert not (tmp_path / "p" / "docs").exists()


def test_archive_refuses_a_bomb_by_its_declared_and_its_actual_size(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "bomb.zip").write_bytes(make_zip({"zeros": b"\0" * 5000, "more": b"\0" * 5000}))
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 8000)
    with pytest.raises(ToolError, match=r"would unpack to more than 8\.0 KB"):
        run(ArchiveTool(), ArchiveInput(path="bomb.zip"), ctx)
    assert not (tmp_path / "bomb").exists()

    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 1_000_000)
    monkeypatch.setattr(archives, "MAX_FILES", 1)
    with pytest.raises(ToolError, match="more than 1 files"):
        run(ArchiveTool(), ArchiveInput(path="bomb.zip"), ctx)

    # Sizes that lie: planned with room, then fewer bytes allowed while unpacking.
    monkeypatch.setattr(archives, "MAX_FILES", 10)
    data = (tmp_path / "bomb.zip").read_bytes()
    plan = archives._plan(data, ArchiveInput(path="bomb.zip"), "bomb", tmp_path)
    monkeypatch.setattr(archives, "MAX_TOTAL_BYTES", 7000)
    with pytest.raises(ToolError, match="unpacked to more than its declared sizes"):
        asyncio.run(archives._extract(data, "bomb.zip", plan, "bomb", tmp_path, ctx))


def test_archive_paths_and_policy(tmp_path: Path, ctx: ToolContext) -> None:
    assert default_destination("downloads/site.tar.gz") == "downloads/site"
    assert default_destination("x.tgz") == "x"
    assert default_destination("data.zip") == "data"
    assert default_destination("blob") == "blob-extracted"
    assert safe_path("./a//b/") == "a/b"
    assert safe_path("a/../../b") is None
    assert safe_path("C:/Windows/x") is None
    assert safe_path("..\\evil") is None
    tool = ArchiveTool()
    assert tool.edited_paths({"path": "dl/site.tar.gz"}) == ["dl/site"]
    assert tool.edited_paths({"path": "a.zip", "to": "vendor/a"}) == ["vendor/a"]
    assert tool.edited_paths({"path": 3}) == []

    (tmp_path / "a.zip").write_bytes(make_zip({"x": b"x"}))
    with pytest.raises(ToolError, match="outside the workspace"):
        run(tool, ArchiveInput(path="a.zip", to="../elsewhere"), ctx)
    (tmp_path / "plain.txt").write_text("hello")
    with pytest.raises(ToolError, match="isn't a zip or tar archive"):
        run(tool, ArchiveInput(path="plain.txt"), ctx)


# -- cron


def cron(ctx: ToolContext, expression: str, after: str, zone: str = "UTC", count: int = 5) -> str:
    args = CronInput(expression=expression, timezone=zone, after=after, count=count)
    return run(CronTool(), args, ctx).content


def runs(text: str) -> list[str]:
    return [line.split("  in ")[0].strip() for line in text.splitlines() if line.startswith("  ")]


@pytest.mark.parametrize(
    ("expression", "words"),
    [
        ("30 9 * * 1-5", "At 09:30 on Monday through Friday"),
        ("*/15 * * * *", "Every 15 minutes"),
        (
            "0 8-18/2 1 * *",
            "At minute 0 past every 2nd hour from 8 through 18 on day 1 of the month",
        ),
        ("0 9,17 * * *", "At 09:00 and 17:00"),
        ("5,35 1 * JAN,jul *", "At minutes 5 and 35 past hour 1 in January and July"),
        ("0 0 * * 7", "At 00:00 on Sunday"),
        ("0 0 13 * FRI", "At 00:00 on day 13 of the month or on Friday"),
        ("*/10 * * * * *", "Every 10 seconds"),
        ("0 30 9 * * MON", "At 09:30:00 on Monday"),
        ("* * * * *", "Every minute"),
        ("10-30/5 * * * *", "Every 5 minutes from 10 through 30"),
        ("0 0 1 */3 *", "At 00:00 on day 1 of the month in every 3rd month"),
    ],
)
def test_cron_explains_an_expression(expression: str, words: str) -> None:
    assert explain(parse(expression)[0]) == words


def test_cron_matches_a_day_when_either_day_field_does(ctx: ToolContext) -> None:
    # 2026-11-01 is a Sunday: the 1st, then Mondays.
    either = cron(ctx, "0 0 1 * MON", after="2026-10-31T12:00", count=3)
    assert runs(either) == [
        "Sun 2026-11-01 00:00 UTC",
        "Mon 2026-11-02 00:00 UTC",
        "Mon 2026-11-09 00:00 UTC",
    ]
    # A day-of-month field starting with * makes it both: odd days that are Mondays.
    both = cron(ctx, "0 0 */2 * MON", after="2026-10-31T12:00", count=3)
    assert runs(both) == [
        "Mon 2026-11-09 00:00 UTC",
        "Mon 2026-11-23 00:00 UTC",
        "Mon 2026-12-07 00:00 UTC",
    ]


def test_cron_follows_daylight_saving_in_new_york(ctx: ToolContext) -> None:
    # The clocks go back at 02:00 EDT on 2026-11-01: 01:00-01:59 comes twice.
    every = cron(ctx, "*/30 * * * *", "2026-11-01T00:45-04:00", "America/New_York", count=5)
    assert runs(every) == [
        "Sun 2026-11-01 01:00 EDT",
        "Sun 2026-11-01 01:30 EDT",
        "Sun 2026-11-01 01:00 EST",
        "Sun 2026-11-01 01:30 EST",
        "Sun 2026-11-01 02:00 EST",
    ]
    fixed = cron(ctx, "30 1 * * *", "2026-11-01T00:00", "America/New_York", count=2)
    assert runs(fixed) == ["Sun 2026-11-01 01:30 EDT", "Mon 2026-11-02 01:30 EST"]
    # They jump forward at 02:00 EST on 2027-03-14: 02:30 doesn't exist that day.
    spring = cron(ctx, "30 2 * * *", "2027-03-13T12:00", "America/New_York", count=2)
    assert runs(spring) == ["Mon 2027-03-15 02:30 EDT", "Tue 2027-03-16 02:30 EDT"]
    assert "No run at 2027-03-14 02:30: that time doesn't exist in America/New_York" in spring
    assert "in 1d 13h" in spring  # counted in real time across the change


def test_cron_macros_seconds_and_impossible_dates(ctx: ToolContext) -> None:
    daily = cron(ctx, "@daily", after="2026-11-24T10:00", count=2)
    assert daily.splitlines()[:2] == ["@daily (= 0 0 * * *)", "At 00:00."]
    assert runs(daily) == ["Wed 2026-11-25 00:00 UTC", "Thu 2026-11-26 00:00 UTC"]
    yearly = cron(ctx, "@annually", after="2026-11-24T10:00", count=1)
    assert runs(yearly) == ["Fri 2027-01-01 00:00 UTC"]
    seconds = cron(ctx, "*/20 * * * * *", after="2026-11-24T10:00:05", count=3)
    assert runs(seconds) == [
        "Tue 2026-11-24 10:00:20 UTC",
        "Tue 2026-11-24 10:00:40 UTC",
        "Tue 2026-11-24 10:01:00 UTC",
    ]
    never = cron(ctx, "0 0 30 2 *", after="2026-11-24T10:00")
    assert "It never runs" in never
    assert "GitHub Actions" not in never  # said only when the zone was left to the machine


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("61 * * * *", "The minute field '61' has 61, out of range: minutes go from 0 to 59"),
        ("* * * *", "has 5 fields .* this one has 4"),
        ("0 0 * * FOO", "day of the week field 'FOO' has 'FOO', which isn't a number, or a name"),
        ("*/0 * * * *", "a step is a whole number above 0"),
        ("5-1 * * * *", "goes backwards"),
        ("0 0 L * *", "L, W and # aren't supported"),
        ("@reboot", "no schedule"),
        ("@sometimes", "isn't a cron macro"),
        ("15 10 * * * 2026", "With six fields the first is seconds"),
    ],
)
def test_cron_points_at_the_bad_field(ctx: ToolContext, expression: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        cron(ctx, expression, after="2026-11-24T10:00")


def test_cron_refuses_an_unknown_time_zone(ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match="isn't a time zone name"):
        cron(ctx, "* * * * *", after="", zone="Mars/Olympus")


# -- OpenAPI

SPEC: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.2.0", "description": "A pet store.\nMore."},
    "servers": [{"url": "http://localhost:8000"}],
    "tags": [{"name": "users"}, {"name": "tree"}],
    "security": [{"bearer": []}],
    "components": {
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
            "key": {"type": "apiKey", "in": "header", "name": "X-Key"},
        },
        "parameters": {
            "UserId": {
                "in": "path",
                "name": "id",
                "required": True,
                "schema": {"type": "integer"},
                "description": "The user's id",
            }
        },
        "schemas": {
            "User": {
                "type": "object",
                "required": ["id", "tags"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string", "nullable": True},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "role": {"$ref": "#/components/schemas/Role"},
                    "created": {"type": "string", "format": "date-time"},
                },
            },
            "Role": {"type": "string", "enum": ["admin", "member"]},
            "NewUser": {
                "allOf": [
                    {
                        "type": "object",
                        "required": ["name"],
                        "properties": {"name": {"type": "string"}},
                    }
                ]
            },
            "Node": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}},
                },
            },
            "Error": {"type": "object", "properties": {"detail": {"type": "string"}}},
        },
    },
    "paths": {
        "/users": {
            "get": {"tags": ["users"], "summary": "List users", "operationId": "listUsers"},
            "post": {
                "tags": ["users"],
                "summary": "Create a user",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/NewUser"}}
                    },
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/users/{id}": {
            "parameters": [{"$ref": "#/components/parameters/UserId"}],
            "get": {
                "tags": ["users"],
                "summary": "Get a user",
                "operationId": "getUser",
                "parameters": [{"in": "query", "name": "verbose", "schema": {"type": "boolean"}}],
                "responses": {
                    "200": {
                        "description": "The user",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/User"}}
                        },
                    },
                    "404": {
                        "description": "No such user",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
                        },
                    },
                },
            },
            "delete": {"tags": ["users"], "summary": "Delete a user", "deprecated": True},
        },
        "/tree": {
            "get": {
                "tags": ["tree"],
                "summary": "The whole tree",
                "security": [],
                "responses": {
                    "200": {
                        "description": "OK",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Node"}}
                        },
                    }
                },
            }
        },
        "/health": {"get": {"summary": "Health check"}},
    },
}


def test_openapi_maps_an_api_from_a_spec_file(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "openapi.json").write_text(json.dumps(SPEC))
    output = run(OpenAPITool(), OpenAPIInput(source="openapi.json"), ctx)
    lines = output.content.splitlines()
    assert lines[0] == "Pets 1.2.0 (OpenAPI 3.0.3, from openapi.json)"
    assert lines[1] == "A pet store."
    assert "Servers: http://localhost:8000" in lines
    assert "  bearer: HTTP bearer (JWT)" in lines
    assert "  key: API key in the header X-Key" in lines
    assert "6 endpoints:" in lines
    assert lines.index("[users]") < lines.index("[tree]") < lines.index("[no tag]")
    assert "  GET     /users/{id}  Get a user" in lines
    assert "  DELETE  /users/{id}  Delete a user (deprecated)" in lines
    assert "  GET     /health      Health check" in lines


def test_openapi_shows_an_endpoint_in_full_with_refs_followed(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "openapi.json").write_text(json.dumps(SPEC))
    tool = OpenAPITool()
    output = run(tool, OpenAPIInput(source="openapi.json", endpoint="GET /users/{id}"), ctx)
    assert output.content.splitlines() == [
        "GET /users/{id} - Get a user",
        "operationId: getUser  tags: users",
        "Auth: bearer",
        "Parameters:",
        "  path   id       integer  required  The user's id",
        "  query  verbose  boolean",
        "Responses:",
        "  200 (application/json): User { id: integer, name?: string | null, tags: string[], "
        'role?: "admin" | "member", created?: string<date-time> }  - The user',
        "  404 (application/json): Error { detail?: string }  - No such user",
    ]

    post = run(tool, OpenAPIInput(source="openapi.json", endpoint="POST /users"), ctx)
    assert "Request body (application/json, required): NewUser { name: string }" in post.content
    assert "  201: Created" in post.content

    tree = run(tool, OpenAPIInput(source="openapi.json", endpoint="/tree"), ctx)
    assert "Auth: none" in tree.content
    assert "200 (application/json): Node { name: string, children?: Node[] }" in tree.content

    by_id = run(tool, OpenAPIInput(source="openapi.json", endpoint="listUsers"), ctx)
    assert by_id.content.startswith("GET /users - List users")


def test_openapi_narrows_by_tag_and_says_when_nothing_matches(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "openapi.json").write_text(json.dumps(SPEC))
    tool = OpenAPITool()
    users = run(tool, OpenAPIInput(source="openapi.json", tag="users"), ctx)
    assert users.content.count("\n\n") == 3  # four operations, each in full
    with pytest.raises(ToolError, match="The tags are: users, tree"):
        run(tool, OpenAPIInput(source="openapi.json", tag="pets"), ctx)
    with pytest.raises(ToolError, match="No endpoint matches"):
        run(tool, OpenAPIInput(source="openapi.json", endpoint="/orders"), ctx)
    (tmp_path / "other.json").write_text('{"name": "not a spec"}')
    with pytest.raises(ToolError, match="doesn't look like an OpenAPI or Swagger spec"):
        run(tool, OpenAPIInput(source="other.json"), ctx)


def test_openapi_reads_swagger_2(tmp_path: Path, ctx: ToolContext) -> None:
    spec = {
        "swagger": "2.0",
        "info": {"title": "Old", "version": "1"},
        "host": "api.example.com",
        "basePath": "/v1",
        "schemes": ["https"],
        "securityDefinitions": {"basic": {"type": "basic"}},
        "definitions": {"Pet": {"type": "object", "properties": {"id": {"type": "integer"}}}},
        "paths": {
            "/pets": {
                "post": {
                    "summary": "Add a pet",
                    "parameters": [
                        {
                            "in": "body",
                            "name": "pet",
                            "required": True,
                            "schema": {"$ref": "#/definitions/Pet"},
                        },
                        {"in": "header", "name": "X-Trace", "type": "string"},
                    ],
                    "responses": {
                        "200": {"description": "OK", "schema": {"$ref": "#/definitions/Pet"}}
                    },
                }
            }
        },
    }
    (tmp_path / "swagger.json").write_text(json.dumps(spec))
    overview = run(OpenAPITool(), OpenAPIInput(source="swagger.json"), ctx)
    assert "Old 1 (Swagger 2.0, from swagger.json)" in overview.content
    assert "Servers: https://api.example.com/v1" in overview.content
    assert "  basic: HTTP basic" in overview.content
    detail = run(OpenAPITool(), OpenAPIInput(source="swagger.json", endpoint="/pets"), ctx)
    assert "  header  X-Trace  string" in detail.content
    assert "Request body, required: Pet { id?: integer }" in detail.content
    assert "  200: Pet { id?: integer }  - OK" in detail.content


@pytest.fixture
def spec_server() -> Iterator[str]:
    body = json.dumps(SPEC).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/openapi.json":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_openapi_fetches_a_spec_from_a_local_server(spec_server: str, ctx: ToolContext) -> None:
    tool = OpenAPITool()
    url = f"{spec_server}/openapi.json"
    output = run(tool, OpenAPIInput(source=url), ctx)
    assert output.content.startswith(f"Pets 1.2.0 (OpenAPI 3.0.3, from {url})")
    assert tool.host({"source": url}) == "127.0.0.1"
    assert tool.host({"source": "openapi.json"}) is None
    assert tool.host({"source": None}) is None
    with pytest.raises(ToolError, match="HTTP 404"):
        run(tool, OpenAPIInput(source=f"{spec_server}/missing"), ctx)


def test_openapi_fetches_only_from_this_machine_and_the_local_network(ctx: ToolContext) -> None:
    async def public(host: str) -> list[str]:
        return ["93.184.215.14"]

    with pytest.raises(ToolError, match="only fetches from this machine and the local network"):
        run(OpenAPITool(resolver=public), OpenAPIInput(source="https://api.example.com/x"), ctx)


def test_openapi_reads_yaml_through_the_projects_python_or_says_to_use_json(
    tmp_path: Path, ctx: ToolContext, python_on_path: None
) -> None:
    (tmp_path / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Tiny\n  version: '1'\npaths:\n  /ping:\n    get:\n"
        "      summary: Ping\n"
    )
    has_yaml = (
        subprocess.run([sys.executable, "-I", "-c", "import yaml"], capture_output=True).returncode
        == 0
    )
    if has_yaml:
        output = run(OpenAPITool(), OpenAPIInput(source="openapi.yaml"), ctx)
        assert "GET     /ping  Ping" in output.content
    else:
        with pytest.raises(ToolError, match=r"needs PyYAML.*Use the JSON version"):
            run(OpenAPITool(), OpenAPIInput(source="openapi.yaml"), ctx)


# -- Imports


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@needs_rg
def test_imports_finds_a_cycle_unused_modules_and_the_most_imported(
    tmp_path: Path, ctx: ToolContext
) -> None:
    write(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "pkg"\n[project.scripts]\npkg = "pkg.cli:main"\n',
            "src/pkg/__init__.py": "",
            "src/pkg/a.py": "import os\nfrom . import b\nfrom .util import helper\n",
            "src/pkg/b.py": "from pkg.a import thing\nimport pkg.util\n",
            "src/pkg/util.py": "import json\n",
            "src/pkg/unused.py": "from .util import helper\n",
            "src/pkg/lazy.py": "def f():\n    from pkg import late\n",
            "src/pkg/late.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from pkg.lazy import f\n",
            "src/pkg/cli.py": "from pkg.a import x\n",
            "src/pkg/sub/__init__.py": "from ..util import helper\n",
            "tests/test_a.py": "from pkg.a import thing\nfrom helpers import h\n",
            "tests/helpers.py": "",
            "scripts/run.py": "import pkg.b\nif __name__ == '__main__':\n    pass\n",
            "broken.py": "def (:\n",
        },
    )
    output = run(ImportsTool(), ImportsInput(), ctx)
    lines = output.content.splitlines()
    assert lines[0] == "Imports in .: 13 Python modules, 12 imports between them."
    assert "(1 couldn't be parsed: broken.py)" in lines
    assert "  pkg.a → pkg.b → pkg.a" in lines
    assert "  pkg.lazy → pkg.late" not in output.content  # lazy and TYPE_CHECKING
    unused = lines[lines.index(next(x for x in lines if x.startswith("Possibly unused"))) :]
    assert "  pkg.unused  (src/pkg/unused.py)" in unused
    assert "  pkg.lazy  (src/pkg/lazy.py)" not in unused  # late imports it, lazily or not
    for kept in ("pkg.cli", "test_a", "run", "pkg.sub", "pkg  "):
        assert not any(line.startswith(f"  {kept}") for line in unused), kept
    top = lines[lines.index("Most imported:") + 1 :]
    assert top[0] == "  4  pkg.util"
    assert top[1] == "  3  pkg.a"


@needs_rg
def test_imports_describes_one_module(tmp_path: Path, ctx: ToolContext) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/api.py": "from app import db\nfrom app.models import User\n",
            "app/db.py": "from .config import settings\n",
            "app/config.py": "",
            "app/models.py": "from app.db import session\n",
            "main.py": "from app.api import router\n",
        },
    )
    output = run(ImportsTool(), ImportsInput(module="app/api.py"), ctx)
    assert output.content.splitlines() == [
        "app.api (app/api.py)",
        "",
        "Imports 2:",
        "  app.db  (app/db.py)",
        "  app.models  (app/models.py)",
        "",
        "Imported by 1:",
        "  main  (main.py)",
        "",
        "Transitive imports: 3 modules, up to 2 levels deep",
        "  longest chain: app.api → app.db → app.config",
        "Everything that imports it, directly or not: 1 modules.",
    ]
    by_name = run(ImportsTool(), ImportsInput(module="app.config"), ctx)
    assert "Imported by 1:\n  app.db  (app/db.py)" in by_name.content
    assert "Everything that imports it, directly or not: 4 modules." in by_name.content
    with pytest.raises(ToolError, match="No module 'nothing'"):
        run(ImportsTool(), ImportsInput(module="nothing"), ctx)


@needs_rg
def test_imports_resolves_typescript_aliases_and_index_files(
    tmp_path: Path, ctx: ToolContext
) -> None:
    write(
        tmp_path,
        {
            "web/tsconfig.json": '{\n  // Next.js\n  "compilerOptions": {\n    "paths": {\n'
            '      "@/*": ["./src/*"], /* the alias */\n    },\n  },\n}\n',
            "web/package.json": '{"name": "web"}',
            "web/src/lib/api.ts": 'export const get = () => fetch("http://x/y");\n',
            "web/src/lib/index.ts": 'export * from "./api";\nexport { fmt } from "./format.js";\n',
            "web/src/lib/format.ts": "export const fmt = 1;\n",
            "web/src/components/Button.tsx": 'import { get } from "../lib/api";\n'
            'import type { Page } from "@/app/page";\nimport React from "react";\n',
            "web/src/app/page.tsx": 'import { get } from "@/lib";\n'
            'import Button from "@/components/Button";\n'
            'const Chart = () => import("@/components/Chart");\n'
            '// import { nope } from "@/orphan";\n',
            "web/src/components/Chart.tsx": 'const { get } = require("../lib/api");\n',
            "web/src/orphan.ts": "export const unused = 1;\n",
            "web/src/lib/api.test.ts": 'import { get } from "./api";\n',
            "web/next.config.ts": "export default {};\n",
        },
    )
    output = run(ImportsTool(), ImportsInput(path="web/src"), ctx)
    lines = output.content.splitlines()
    assert lines[0] == "Imports in web/src: 8 JS/TS files, 9 imports between them."
    assert "No circular imports." in lines  # Button → page is type-only
    start = lines.index(next(x for x in lines if x.startswith("Possibly unused")))
    unused = lines[start : lines.index("", start)]
    assert unused[1:] == ["  web/src/orphan.ts"]
    assert "  4  web/src/lib/api.ts" in lines

    page = run(ImportsTool(), ImportsInput(path="web/src", module="web/src/app/page.tsx"), ctx)
    assert "Imports 3:" in page.content
    assert "  web/src/components/Chart.tsx  (lazy or type-only)" in page.content
    assert "  web/src/lib/index.ts" in page.content


def test_import_helpers() -> None:
    assert strongly_connected({"a": ["b"], "b": ["c", "a"], "c": ["c"], "d": []}) == [
        ["c"],
        ["b", "a"],
        ["d"],
    ]
    assert (
        strip_comments('a // c\nb /* x\ny */ "// kept" `/* too */`')
        == 'a \nb \n "// kept" `/* too */`'
    )
    assert parse_jsonc('{"a": [1, 2,], /* c */ "b": "http://x",}') == {"a": [1, 2], "b": "http://x"}
