# ruff: noqa: E501  (expected output, a page and a script, kept whole)
"""PDFs and notebooks in Read, NotebookEdit, Packages, Http, Database, Logs, Profile, coverage
in RunTests, and Browser."""

import asyncio
import base64
import json
import os
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx
import pytest

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.browser import BrowserInput, BrowserTool
from zwans.tools.browser import available as browser_available
from zwans.tools.database import DatabaseInput, DatabaseTool
from zwans.tools.http import HttpInput, HttpTool
from zwans.tools.logs import LogsInput, LogsTool, shape
from zwans.tools.notebook_edit import NotebookEditInput, NotebookEditTool
from zwans.tools.packages import PackagesInput, PackagesTool
from zwans.tools.profile import ProfileInput, ProfileTool
from zwans.tools.read import ReadInput, ReadTool
from zwans.tools.run_tests import RunTestsInput, RunTestsTool


def run(tool: Any, args: Any, ctx: ToolContext) -> ToolOutput:
    output: ToolOutput = asyncio.run(tool.run(args, ctx))
    return output


# -- PDFs


def make_pdf(pages: list[str]) -> bytes:
    """A PDF with a line of Helvetica on each page, written out by hand."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [{}] /Count {} >>".format(
            " ".join(f"{4 + 2 * n} 0 R" for n in range(len(pages))), len(pages)
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for n, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
        objects.append(
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * n} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out + trailer.encode()


def test_a_pdf_is_read_as_its_text_page_by_page(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "spec.pdf").write_bytes(make_pdf(["Retries are off by default.", "", "Page three"]))

    output = run(ReadTool(), ReadInput(path="spec.pdf"), ctx)
    assert output.content.startswith("spec.pdf: a PDF of 3 pages.")
    assert "--- Page 1 ---\nRetries are off by default." in output.content
    assert "--- Page 2 ---\n(No text on this page.)" in output.content

    third = run(ReadTool(), ReadInput(path="spec.pdf", pages="3"), ctx)
    assert "--- Page 3 ---\nPage three" in third.content and "Page 1" not in third.content
    assert "(Showing pages" not in third.content
    with pytest.raises(ToolError, match="The PDF has 3 pages"):
        run(ReadTool(), ReadInput(path="spec.pdf", pages="9"), ctx)
    with pytest.raises(ToolError, match="pages should be a page or a range"):
        run(ReadTool(), ReadInput(path="spec.pdf", pages="first"), ctx)


def test_a_long_pdf_says_which_pages_come_next(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "book.pdf").write_bytes(make_pdf([f"Chapter {n}" for n in range(1, 26)]))

    output = run(ReadTool(), ReadInput(path="book.pdf"), ctx)
    assert "--- Page 20 ---" in output.content and "--- Page 21 ---" not in output.content
    assert output.content.endswith(
        '(Showing pages 1-20 of 25. Ask for more with pages, as "21-25".)'
    )


# -- notebooks

PNG = b"\x89PNG\r\n\x1a\n" + bytes(24)


def notebook() -> dict[str, Any]:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"language": "python", "name": "python3"}},
        "cells": [
            {
                "id": "intro",
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# Sales\n", "By month."],
            },
            {
                "id": "load",
                "cell_type": "code",
                "metadata": {},
                "execution_count": 3,
                "source": ["import pandas as pd\n", "df = pd.read_csv('sales.csv')\n", "df.plot()"],
                "outputs": [
                    {"output_type": "stream", "name": "stdout", "text": ["12 rows\n"]},
                    {
                        "output_type": "display_data",
                        "metadata": {},
                        "data": {
                            "image/png": base64.b64encode(PNG).decode(),
                            "text/plain": ["<Figure size 640x480 with 1 Axes>"],
                        },
                    },
                ],
            },
        ],
    }


def test_a_notebook_is_read_as_cells_with_outputs(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "sales.ipynb").write_text(json.dumps(notebook()))

    output = run(ReadTool(), ReadInput(path="sales.ipynb"), ctx)
    assert output.content.splitlines()[:4] == [
        "sales.ipynb: a notebook of 2 cells, in python.",
        "",
        "[cell 0: markdown, id intro]",
        "# Sales",
    ]
    assert "[cell 1: code, id load, run 3]\nimport pandas as pd" in output.content
    assert "[output]\n12 rows" in output.content
    assert "[output: a picture, attached]" in output.content and "<Figure" not in output.content
    assert len(output.images) == 1


def test_notebook_cells_are_replaced_inserted_and_deleted(tmp_path: Path, ctx: ToolContext) -> None:
    path = tmp_path / "sales.ipynb"
    path.write_text(json.dumps(notebook()))
    tool = NotebookEditTool()

    preview = asyncio.run(
        tool.preview(NotebookEditInput(path="sales.ipynb", cell=1, source="df = 1"), ctx)
    )
    assert "-import pandas as pd" in preview and "+df = 1" in preview
    assert json.loads(path.read_text()) == notebook()  # a preview changes nothing

    replaced = run(
        tool, NotebookEditInput(path="sales.ipynb", cell="load", source="x = 1\ny = 2"), ctx
    )
    assert replaced.content == "Replaced cell 1 of sales.ipynb."
    cell = json.loads(path.read_text())["cells"][1]
    assert cell["source"] == ["x = 1\n", "y = 2"] and cell["outputs"] == []
    assert cell["execution_count"] is None and cell["id"] == "load"

    inserted = run(
        tool,
        NotebookEditInput(
            path="sales.ipynb", cell=2, action="insert", source="Notes", cell_type="markdown"
        ),
        ctx,
    )
    assert inserted.content == "Inserted a markdown cell at 2 in sales.ipynb."
    cells = json.loads(path.read_text())["cells"]
    assert cells[2]["cell_type"] == "markdown" and len(cells[2]["id"]) == 8

    changed = run(
        tool,
        NotebookEditInput(path="sales.ipynb", cell=0, source="print(1)", cell_type="code"),
        ctx,
    )
    assert changed.content == "Replaced cell 0 of sales.ipynb, now a code cell."
    assert json.loads(path.read_text())["cells"][0]["id"] == "intro"

    deleted = run(tool, NotebookEditInput(path="sales.ipynb", cell=2, action="delete"), ctx)
    assert deleted.content == "Deleted cell 2 of sales.ipynb." and "-Notes" in (deleted.diff or "")
    assert len(json.loads(path.read_text())["cells"]) == 2
    assert path.read_text().endswith("}\n")

    with pytest.raises(ToolError, match="There is no cell 5: the cells are numbered 0 to 1"):
        run(tool, NotebookEditInput(path="sales.ipynb", cell=5, source="x"), ctx)
    with pytest.raises(ToolError, match="no cell with the id 'nope'"):
        run(tool, NotebookEditInput(path="sales.ipynb", cell="nope", source="x"), ctx)


# -- Packages

PYPI = {
    "info": {
        "name": "httpx",
        "version": "0.28.1",
        "summary": "The next generation HTTP client.",
        "requires_python": ">=3.8",
        "license_expression": "BSD-3-Clause",
        "project_urls": {"Changelog": "https://github.com/encode/httpx/blob/master/CHANGELOG.md"},
    },
    "releases": {
        "0.27.0": [{"upload_time": "2024-02-21T10:00:00"}],
        "0.28.0": [{"upload_time": "2024-11-28T10:00:00"}],
        "0.28.1": [{"upload_time": "2024-12-06T10:00:00"}],
        "0.1.0": [],
    },
}


def registry(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if url == "https://pypi.org/pypi/httpx/json":
        return httpx.Response(200, json=PYPI)
    if url == "https://api.osv.dev/v1/query":
        asked = json.loads(request.content)
        if asked["version"] == "0.27.0":
            vuln = {
                "id": "GHSA-xxxx",
                "aliases": ["CVE-2024-0001"],
                "summary": "Headers leak on redirect",
                "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "0.28.0"}]}]}],
            }
            return httpx.Response(200, json={"vulns": [vuln]})
        return httpx.Response(200, json={})
    if url.startswith("https://api.github.com/repos/encode/httpx/releases"):
        release = {
            "tag_name": "0.28.1",
            "name": "Version 0.28.1",
            "published_at": "2024-12-06T00:00:00Z",
            "body": "- Fix verify=False",
        }
        return httpx.Response(200, json=[release])
    if url == "https://registry.npmjs.org/@scope%2Fwidget":
        assert request.headers["accept"] == "application/vnd.npm.install-v1+json"
        versions = {"1.0.0": {}, "2.0.0-beta.1": {}, "1.1.0": {"deprecated": "use 2"}}
        return httpx.Response(
            200,
            json={
                "dist-tags": {"latest": "1.1.0"},
                "versions": versions,
                "modified": "2025-01-02T00:00:00Z",
            },
        )
    if url == "https://registry.npmjs.org/@scope%2Fwidget/1.1.0":
        return httpx.Response(
            200, json={"description": "A widget.", "license": "MIT", "engines": {"node": ">=18"}}
        )
    return httpx.Response(404)


def test_a_pypi_package_with_its_versions_notes_and_vulnerabilities(ctx: ToolContext) -> None:
    tool = PackagesTool(transport=httpx.MockTransport(registry))

    latest = run(tool, PackagesInput(name="httpx"), ctx).content
    assert latest.splitlines()[:5] == [
        "httpx on PyPI: latest 0.28.1, released 2024-12-06",
        "The next generation HTTP client.",
        "Requires Python >=3.8. License BSD-3-Clause.",
        "Recent versions: 0.28.1 (2024-12-06), 0.28.0 (2024-11-28), 0.27.0 (2024-02-21)",
        "Changelog: https://github.com/encode/httpx/blob/master/CHANGELOG.md",
    ]
    assert "Known vulnerabilities in 0.28.1: none on OSV.dev." in latest
    assert (
        "Releases on GitHub (encode/httpx): 0.28.1 (2024-12-06)\nNotes for Version 0.28.1:\n- Fix verify=False"
        in latest
    )

    old = run(tool, PackagesInput(name="httpx", version="0.27.0"), ctx).content
    assert (
        "Known vulnerabilities in 0.27.0 (1 on OSV.dev):\n- GHSA-xxxx / CVE-2024-0001: Headers leak on redirect Fixed in 0.28.0."
        in old
    )

    with pytest.raises(ToolError, match="PyPI has no package by that name"):
        run(tool, PackagesInput(name="nope"), ctx)
    assert tool.host({"name": "x", "ecosystem": "npm"}) == "registry.npmjs.org"
    assert tool.host({"name": "x"}) == "pypi.org"


def test_an_npm_package_without_downloading_every_version(ctx: ToolContext) -> None:
    tool = PackagesTool(transport=httpx.MockTransport(registry))
    output = run(tool, PackagesInput(name="@scope/widget", ecosystem="npm"), ctx).content

    assert output.splitlines()[:5] == [
        "@scope/widget on npm: latest 1.1.0, released package last changed 2025-01-02",
        "Warning: 1.1.0 is deprecated: use 2",
        "A widget.",
        "Requires Node >=18. License MIT.",
        "Recent versions: 1.1.0, 1.0.0",
    ]


# -- Http


async def local(host: str) -> list[str]:
    return ["127.0.0.1"] if host in ("localhost", "app.test") else ["93.184.216.34"]


def test_http_shows_status_headers_and_json_laid_out(ctx: ToolContext) -> None:
    seen: list[httpx.Request] = []

    def server(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": 7, "tags": ["a"]}, headers={"location": "/items/7"})

    tool = HttpTool(transport=httpx.MockTransport(server), resolver=local)
    args = HttpInput.model_validate(
        {"url": "http://localhost:8000/items", "method": "POST", "json": {"name": "pen"}}
    )
    output = run(tool, args, ctx).content

    assert output.splitlines()[0].startswith("HTTP 201 Created (")
    assert "content-type: application/json\ncontent-length: 21\nlocation: /items/7" in output
    assert output.endswith('{\n  "id": 7,\n  "tags": [\n    "a"\n  ]\n}')
    assert json.loads(seen[0].content) == {"name": "pen"}
    assert tool.host({"url": "http://localhost:8000/x"}) == "localhost"


def test_http_only_reaches_local_servers(ctx: ToolContext) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    tool = HttpTool(transport=httpx.MockTransport(refused), resolver=local)
    with pytest.raises(ToolError, match=r"example\.com is on the public internet"):
        run(tool, HttpInput(url="https://example.com/"), ctx)
    with pytest.raises(ToolError, match=r"Nothing answered .* is the server running on port 3000"):
        run(tool, HttpInput(url="http://localhost:3000/"), ctx)
    with pytest.raises(ToolError, match="needs http or https"):
        run(tool, HttpInput(url="ftp://localhost/"), ctx)


# -- Database


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    path = tmp_path / "shop.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL)")
        db.executemany(
            "INSERT INTO items (name, price) VALUES (?, ?)",
            [("pen; blue", 1.5), ("cup", None)] + [(f"item {n}", n) for n in range(300)],
        )
    return path


needs_sqlite = pytest.mark.skipif(not shutil.which("sqlite3"), reason="needs sqlite3")


@needs_sqlite
def test_a_sqlite_database_is_listed_and_queried(shop: Path, ctx: ToolContext) -> None:
    tool = DatabaseTool()

    schema = run(tool, DatabaseInput(path="shop.db"), ctx).content
    assert schema == (
        "shop.db: 1 tables and views.\n\n"
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL);"
    )
    rows = run(
        tool,
        DatabaseInput(path="shop.db", query="SELECT name, price FROM items WHERE id <= 2;"),
        ctx,
    )
    assert rows.content == (
        "name      | price\n"
        "----------+------\n"
        "pen; blue | 1.5\n"
        "cup       | NULL\n"
        "(2 rows, from shop.db.)"
    )
    many = run(tool, DatabaseInput(path="shop.db", query="SELECT id FROM items"), ctx).content
    assert many.endswith("(The first 200 rows; there are more, from shop.db.)")


@needs_sqlite
def test_the_database_tool_only_reads(shop: Path, ctx: ToolContext) -> None:
    tool = DatabaseTool()
    with pytest.raises(ToolError, match="Database only reads, and DELETE doesn't"):
        run(tool, DatabaseInput(path="shop.db", query="DELETE FROM items"), ctx)
    with pytest.raises(ToolError, match="one statement at a time"):
        run(tool, DatabaseInput(path="shop.db", query="SELECT 1; DROP TABLE items"), ctx)
    with pytest.raises(ToolError, match=r"readonly|read-only|attempt to write"):
        run(tool, DatabaseInput(path="shop.db", query="PRAGMA user_version = 3"), ctx)
    with pytest.raises(ToolError, match="no such table"):
        run(tool, DatabaseInput(path="shop.db", query="SELECT * FROM missing_table"), ctx)
    with pytest.raises(ToolError, match="the environment variable that holds the address"):
        run(tool, DatabaseInput(env="postgres://u:p@h/db"), ctx)


def test_postgres_runs_alone_in_a_read_only_transaction(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path.parent / f"{tmp_path.name}-bin"
    bin_dir.mkdir()
    psql = bin_dir / "psql"
    psql.write_text(
        '#!/bin/sh\nfor arg in "$@"; do echo "$arg"; done > "$(dirname "$0")/args"\n'
        'printf "name,price\\npen,1.5\\n"\n'
    )
    psql.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("SHOP_URL", raising=False)

    with pytest.raises(ToolError, match="SHOP_URL isn't set where commands run"):
        run(DatabaseTool(), DatabaseInput(env="SHOP_URL", query="SELECT 1"), ctx)
    monkeypatch.setenv("SHOP_URL", "postgres://user:secret@db/shop")
    output = run(
        DatabaseTool(), DatabaseInput(env="SHOP_URL", query="SELECT name, price FROM items"), ctx
    )

    assert output.content.startswith("name | price\n-----+------\npen  | 1.5")
    assert output.content.endswith("(1 rows, from $SHOP_URL.)")
    args = (bin_dir / "args").read_text().splitlines()
    assert args[0] == "postgres://user:secret@db/shop"  # from the variable, not the call
    assert args[args.index("BEGIN READ ONLY") + 2].startswith("SELECT * FROM (SELECT name")
    assert args[-1] == "ROLLBACK"


# -- Logs

LOG = """2025-01-02 10:00:01 INFO request GET /items/12 took 31ms
2025-01-02 10:00:02 INFO request GET /items/99 took 4ms
2025-01-02 10:00:03 WARNING cache miss for user 'ann'
2025-01-02 10:00:04 INFO request GET /items/7 took 12ms
2025-01-02 10:00:05 ERROR payment failed for order 5531
Traceback (most recent call last):
  File "app.py", line 3, in pay
    charge()
ValueError: card declined
2025-01-02 10:00:06 ERROR payment failed for order 5532
2025-01-02 10:00:07 WARNING cache miss for user 'bob'
"""


def test_a_log_is_grouped_into_kinds_of_line(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "app.log").write_text(LOG)

    output = run(LogsTool(), LogsInput(path="app.log"), ctx).content
    assert output.splitlines() == [
        "app.log: 11 lines, of 4 kinds.",
        "",
        "Errors and warnings (3 kinds, first seen first):",
        "      2x ERROR 2025-01-02 10:00:05 ERROR payment failed for order 5531  (lines 5-10)",
        "      1x ERROR ValueError: card declined  (line 6)",
        "          Traceback (most recent call last):",
        '            File "app.py", line 3, in pay',
        "              charge()",
        "          ValueError: card declined",
        "      2x WARN  2025-01-02 10:00:03 WARNING cache miss for user 'ann'  (lines 3-11)",
        "",
        "Other lines (1 kinds, most frequent first):",
        "      3x 2025-01-02 10:00:01 INFO request GET /items/12 took 31ms  (lines 1-4)",
    ]
    only = run(LogsTool(), LogsInput(path="app.log", pattern="cache"), ctx).content
    assert only.startswith("app.log: 11 lines, 2 matching 'cache', of 1 kinds.")
    assert (
        shape("10:00:01 GET /a/12 in 3.5ms from 10.0.0.1:80 id 0xff")
        == "GET /a/<n> in <n> from <ip> id <hex>"
    )


# -- Profile


def test_a_profile_says_where_the_time_went(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "slow.py").write_text(
        "import sys\n\ndef busy(n):\n    return sum(i * i for i in range(n))\n\n"
        "def main():\n    for _ in range(20):\n        busy(20000)\n    print('done', sys.argv[1])\n\n"
        "main()\n"
    )
    tool = ProfileTool()
    output = run(tool, ProfileInput(target="python slow.py fast", top=5), ctx).content

    assert output.startswith("The run took ")
    assert "By their own time:" in output and "Including what they called:" in output
    assert "busy (slow.py:3)" in output and "main (slow.py:6)" in output
    assert output.endswith("What it printed:\ndone fast")
    assert not list(tmp_path.glob(".zwans-profile-*"))
    assert tool.commands({"target": "slow.py fast"}) == ["python slow.py fast"]

    with pytest.raises(ToolError, match="No profile came out"):
        run(tool, ProfileInput(target="missing.py"), ctx)


# -- coverage


def test_run_tests_reports_the_lines_tests_never_ran(tmp_path: Path, ctx: ToolContext) -> None:
    pytest.importorskip("coverage")
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    )
    (tmp_path / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    tool = RunTestsTool(tmp_path)

    output = run(tool, RunTestsInput(coverage=True), ctx).content
    assert output.startswith("All tests passed.")
    assert (
        "## Coverage (pytest): files with lines the tests never ran, least covered first" in output
    )
    assert "calc.py" in output and "6" in output.split("calc.py", 1)[1].splitlines()[0]
    assert not (tmp_path / ".zwans-coverage").exists()
    commands = tool.commands({"coverage": True})
    assert commands[0].startswith("python -m coverage run --data-file=.zwans-coverage -m pytest")
    assert commands[1].startswith("python -m coverage report")


# -- the policy


def test_the_policy_knows_the_new_tools(tmp_path: Path) -> None:
    policy = Policy.default()
    policy.add(PolicyFile(mode="ask", deny=["Read(private/**)"]), "test")
    executor = LocalExecutor(tmp_path)
    permissions = Permissions(policy, lambda path: True, executor.relative, root=executor.root)

    def decide(tool: Any, args: dict[str, Any]) -> Decision:
        return permissions.check(tool, args).decision

    assert decide(LogsTool(), {"path": "private/app.log"}) == Decision.DENY
    assert decide(DatabaseTool(), {"path": "private/shop.db"}) == Decision.DENY
    assert decide(DatabaseTool(), {"path": "shop.db"}) == Decision.ALLOW
    assert decide(NotebookEditTool(), {"path": "a.ipynb", "cell": 0}) == Decision.ASK
    assert decide(HttpTool(), {"url": "http://localhost:3000/"}) == Decision.ASK
    assert decide(ProfileTool(), {"target": "slow.py"}) == Decision.ASK


# -- Browser

PAGE = b"""<!doctype html><html><head><title>Shop</title></head><body>
<nav aria-label="Main"><a href="/">Home</a> <a href="/cart">Cart</a></nav>
<main><h1>Find a pen</h1>
<p>Type a name and press Search.</p>
<label for="q">Name</label> <input id="q" placeholder="e.g. blue">
<select id="size"><option>Small</option><option>Large</option></select>
<button id="go" onclick="search()">Search</button>
<ul id="results"></ul>
<div hidden>Secret text</div></main>
<script>
function search() {
  const q = document.getElementById("q").value;
  document.getElementById("results").innerHTML = "<li>Found " + q + " (" + document.getElementById("size").value + ")</li>";
  console.error("search is slow");
  fetch("/missing");
}
</script></body></html>"""


@pytest.fixture
def site() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            found = self.path == "/"
            self.send_response(200 if found else 404)
            self.send_header("content-type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE if found else b"not here")

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.mark.skipif(not browser_available(), reason="needs playwright")
def test_the_browser_reads_a_page_as_an_outline_and_uses_it(site: str, ctx: ToolContext) -> None:
    tool = BrowserTool()

    async def session() -> list[ToolOutput]:
        try:
            opened = await tool.run(BrowserInput(action="open", url=site), ctx)
            typed = await tool.run(BrowserInput(action="type", ref="e3", text="pen"), ctx)
            chosen = await tool.run(BrowserInput(action="select", ref="e4", text="Large"), ctx)
            clicked = await tool.run(BrowserInput(action="click", ref="e5"), ctx)
            shot = await tool.run(BrowserInput(action="screenshot"), ctx)
            assert tool.host({"action": "click", "ref": "e5"}) == "127.0.0.1"
            closed = await tool.run(BrowserInput(action="close"), ctx)
            return [opened, typed, chosen, clicked, shot, closed]
        finally:
            await tool.aclose()

    opened, typed, chosen, clicked, shot, closed = asyncio.run(session())
    assert opened.content.splitlines() == [
        f"Shop — {site}",
        "",
        'navigation "Main":',
        '  link "Home" [e1] → /',
        '  link "Cart" [e2] → /cart',
        "main:",
        "  # Find a pen",
        "  Type a name and press Search.",
        "  Name",
        '  textbox "Name" [e3] placeholder "e.g. blue"',
        '  select [e4] selected "Small", options: Small | Large',
        '  button "Search" [e5]',
    ]
    assert 'textbox "Name" [e3] placeholder "e.g. blue", value "pen"' in typed.content
    assert 'selected "Large"' in chosen.content
    assert "  - Found pen (Large)" in clicked.content
    assert "- console error: search is slow" in clicked.content
    assert f"- HTTP 404: GET {site}missing" in clicked.content
    assert shot.images and shot.images[0].source.media_type == "image/jpeg"
    assert closed.content == "Closed the browser."
    assert tool.host({"action": "open", "url": site}) == "127.0.0.1"
