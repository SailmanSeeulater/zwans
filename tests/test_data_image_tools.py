# ruff: noqa: E501  (a page, a workbook and expected output, kept whole)
"""Data (CSV, TSV, JSON Lines, JSON, Excel and Parquet), ImageDiff, and the Browser's audit."""

import asyncio
import base64
import json
import os
import shutil
import struct
import subprocess
import threading
import zipfile
import zlib
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from zwans.tools import data as data_module
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.browser import BrowserInput, BrowserTool
from zwans.tools.browser import available as browser_available
from zwans.tools.data import DataInput, DataTool
from zwans.tools.image_diff import (
    ImageDiffInput,
    ImageDiffTool,
    decode_png,
    encode_png,
)


def run(tool: Any, args: Any, ctx: ToolContext) -> ToolOutput:
    output: ToolOutput = asyncio.run(tool.run(args, ctx))
    return output


def data(path: str, ctx: ToolContext, **kwargs: Any) -> str:
    return run(DataTool(), DataInput(path=path, **kwargs), ctx).content


def row_of(text: str, name: str) -> list[str]:
    """The cells of a column's line in the statistics table, split on runs of spaces."""
    for line in text.splitlines():
        if line.startswith(name + " "):
            return [cell.strip() for cell in line.split("  ") if cell.strip()]
    raise AssertionError(f"no row for {name} in:\n{text}")


# -- Data: delimited text


def test_data_summarizes_a_csv_with_a_bom_and_quoted_fields(
    tmp_path: Path, ctx: ToolContext
) -> None:
    lines = ["﻿id,name,city,score,joined,active,notes"]
    cities = ["London", "Paris", "Rome", "Rome"]
    for n in range(1, 101):
        notes = '"a note, with a comma"' if n % 2 else ""
        lines.append(
            f'{n},"Person {n}",{cities[n % 4]},{n / 2},2024-01-{n % 28 + 1:02d},'
            f"{'true' if n % 3 else 'false'},{notes}"
        )
    lines.append('101,"Odd, One",Rome,unknown,2024-02-01,true,')
    (tmp_path / "people.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    text = data("people.csv", ctx)

    assert text.splitlines()[0] == (
        "people.csv: CSV (comma-separated, the first row is the header), 101 rows x 7 columns."
    )
    assert row_of(text, "id")[:4] == ["id", "integer", "0", "101"]
    assert "min 1, max 101, mean 51" in row_of(text, "id")[4]
    assert row_of(text, "city")[1:4] == ["text", "0", "3"]
    assert "top: 'Rome' 51, 'Paris' 25, 'London' 25" in text
    score = row_of(text, "score")
    assert score[1] == "number" and "1 not number, as 'unknown'" in score[4]
    assert "from 2024-01-01 to 2024-02-01" in row_of(text, "joined")[4]
    assert row_of(text, "active")[1] == "boolean"
    assert row_of(text, "notes")[1:3] == ["text", "51"]
    assert "First 5 rows:" in text
    assert "1  Person 1  Paris" in text


def test_data_reads_a_tsv_without_a_header_and_focuses_on_columns(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "nums.tsv").write_text("1\t2.5\tfoo\n3\t4.5\tbar\n5\t\tbaz\n")

    text = data("nums.tsv", ctx, columns=["Column 2"], rows=2)

    assert "TSV (tab-separated, no header row, columns numbered), 3 rows x 3 columns." in text
    assert row_of(text, "column 2")[1:4] == ["number", "1", "2"]
    assert "column 1" not in text.split("First")[0].split("\n", 2)[2]
    assert text.splitlines()[-2:] == ["     2.5", "     4.5"]
    with pytest.raises(ToolError, match="No column named nope"):
        data("nums.tsv", ctx, columns=["nope"])


def test_data_sniffs_a_semicolon_delimiter(tmp_path: Path, ctx: ToolContext) -> None:
    (tmp_path / "eu.csv").write_text('name;price\n"Tea; green";3.5\nCoffee;4\n')
    text = data("eu.csv", ctx)
    assert "semicolon-separated" in text
    assert row_of(text, "price")[1] == "number"
    assert "Tea; green" in text


def test_data_reads_only_the_start_of_a_big_file(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(data_module, "MAX_BYTES", 1_000)
    (tmp_path / "big.csv").write_text("n,word\n" + "".join(f"{n},w{n}\n" for n in range(1_000)))

    text = data("big.csv", ctx)

    assert "Only the first" in text and "were read" in text
    rows = int(text.splitlines()[0].split(" rows x ")[0].rsplit(" ", 1)[1].replace(",", ""))
    assert 100 < rows < 200  # whole rows from the first 1,000 bytes


# -- Data: JSON


def test_data_reads_json_lines_with_nested_values_and_a_bad_line(
    tmp_path: Path, ctx: ToolContext
) -> None:
    records = [{"a": n, "b": {"x": n}, "tags": ["t"]} if n % 2 else {"a": n} for n in range(6)]
    lines = [json.dumps(r) for r in records] + ["not json"]
    (tmp_path / "events.jsonl").write_text("\n".join(lines) + "\n")

    text = data("events.jsonl", ctx)

    assert text.splitlines()[0] == (
        "events.jsonl: JSON Lines (1 line isn't JSON, the first at line 7), 6 rows x 3 columns."
    )
    assert row_of(text, "a")[1:4] == ["integer", "0", "6"]
    assert row_of(text, "b")[1:3] == ["object", "3"]
    assert row_of(text, "tags")[1] == "list"
    assert '{"x": 1}' in text


def test_data_reads_a_json_array_inside_an_object(tmp_path: Path, ctx: ToolContext) -> None:
    items = [{"k": n, "at": f"2024-03-01T10:00:{n:02d}Z"} for n in range(12)]
    (tmp_path / "items.json").write_text(json.dumps({"count": 12, "items": items}))

    text = data("items.json", ctx, rows=0)

    assert 'a JSON array of records under "items", 12 rows x 2 columns.' in text
    assert "from 2024-03-01 10:00:00Z to 2024-03-01 10:00:11Z" in row_of(text, "at")[4]
    assert "First" not in text
    (tmp_path / "one.json").write_text('{"name": "x"}')
    with pytest.raises(ToolError, match="no list of records"):
        data("one.json", ctx)


# -- Data: Excel


def make_xlsx(path: Path) -> None:
    """A workbook with two sheets, written by hand: shared and inline strings, numbers, a
    boolean, and a date stored as a number with a date style."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    workbook = (
        f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
        '<sheet name="Orders" sheetId="1" r:id="rId1"/>'
        '<sheet name="Notes" sheetId="2" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/>'
        '<Relationship Id="rId2" Target="/xl/worksheets/notes.xml" Type="x"/>'
        "</Relationships>"
    )
    shared = (
        f'<sst xmlns="{main}"><si><t>item</t></si><si><t>qty</t></si><si><t>shipped</t></si>'
        "<si><t>when</t></si><si><r><t>Pen</t></r><r><t>cil</t></r></si><si><t>Ink</t></si></sst>"
    )
    styles = (
        f'<styleSheet xmlns="{main}"><cellXfs count="2">'
        '<xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
    )
    rows = [
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c></row>'
    ]
    for n in range(2, 8):
        item = (
            '<c r="A{0}" t="s"><v>4</v></c>'
            if n % 2
            else '<c r="A{0}" t="inlineStr"><is><t>Ink pot</t></is></c>'
        )
        rows.append(
            f'<row r="{n}">'
            + item.format(n)
            + f'<c r="B{n}"><v>{n * 1.5 if n == 7 else n}</v></c>'
            + f'<c r="C{n}" t="b"><v>{n % 2}</v></c>'
            + f'<c r="D{n}" s="1"><v>{45292 + n}</v></c>'
            + "</row>"
        )
    sheet1 = f'<worksheet xmlns="{main}"><sheetData>{"".join(rows)}</sheetData></worksheet>'
    notes = (
        f'<worksheet xmlns="{main}"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>note'
        '</t></is></c></row><row r="2"><c r="A2" t="inlineStr"><is><t>hello</t></is></c></row>'
        "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w") as book:
        book.writestr("[Content_Types].xml", "<Types/>")
        book.writestr("xl/workbook.xml", workbook)
        book.writestr("xl/_rels/workbook.xml.rels", rels)
        book.writestr("xl/sharedStrings.xml", shared)
        book.writestr("xl/styles.xml", styles)
        book.writestr("xl/worksheets/sheet1.xml", sheet1)
        book.writestr("xl/worksheets/notes.xml", notes)


def test_data_reads_an_excel_workbook(tmp_path: Path, ctx: ToolContext) -> None:
    make_xlsx(tmp_path / "orders.xlsx")

    text = data("orders.xlsx", ctx)

    assert text.splitlines()[:2] == [
        "orders.xlsx: Excel workbook, 6 rows x 4 columns.",
        "Sheets: Orders (shown), Notes",
    ]
    assert "top: 'Ink pot' 3, 'Pencil' 3" in row_of(text, "item")[4]
    qty = row_of(text, "qty")
    assert qty[1] == "number" and "min 2, max 10.5" in qty[4]
    assert "true 3, false 3" in row_of(text, "shipped")[4]
    assert "from 2024-01-03 to 2024-01-08" in row_of(text, "when")[4]
    assert "Pencil     3  true     2024-01-04" in text

    notes = data("orders.xlsx", ctx, sheet="notes")
    assert "1 rows x 1 columns" in notes and "Notes (shown)" in notes
    assert data("orders.xlsx", ctx, sheet="2") == notes
    with pytest.raises(ToolError, match=r"There's no sheet 'Prices'\. Sheets: Orders, Notes\."):
        data("orders.xlsx", ctx, sheet="Prices")


# -- Data: Parquet


def test_data_reads_parquet_through_the_projects_python(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = {
        "engine": "pyarrow",
        "schema": [["id", "int64"], ["name", "string"]],
        "total": 10_000,
        "rows": [{"id": n, "name": f"n{n % 3}"} for n in range(50)],
    }
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "python"
    fake.write_text(f"#!/bin/sh\necho 'noise'\necho 'ZWANS-PARQUET {json.dumps(found)}'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / "t.parquet").write_bytes(b"PAR1....PAR1")

    text = data("t.parquet", ctx, rows=2)

    assert text.splitlines()[:2] == [
        "t.parquet: Parquet (read with pyarrow), 10,000 rows x 2 columns.",
        "Column statistics come from the first 50 rows.",
    ]
    assert row_of(text, "id")[1:2] == ["int64 (integer)"]
    assert row_of(text, "name")[1:4] == ["string (text)", "0", "3"]


def _has_parquet_reader() -> bool:
    script = "import importlib.util as u, sys; sys.exit(any(u.find_spec(m) for m in ('pyarrow', 'pandas', 'duckdb')))"
    python = shutil.which("python") or shutil.which("python3") or "python3"
    return subprocess.run([python, "-c", script]).returncode != 0


@pytest.mark.skipif(_has_parquet_reader(), reason="a Parquet reader is installed")
def test_data_says_what_parquet_needs_when_nothing_can_read_it(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "t.parquet").write_bytes(b"PAR1....PAR1")
    with pytest.raises(ToolError, match="needs pyarrow, pandas or duckdb"):
        data("t.parquet", ctx)


# -- ImageDiff


def canvas(width: int, height: int, color: tuple[int, int, int] = (255, 255, 255)) -> bytearray:
    return bytearray(bytes(color) * (width * height))


def paint(
    pixels: bytearray, width: int, box: tuple[int, int, int, int], color: tuple[int, int, int]
) -> None:
    x, y, w, h = box
    for row in range(y, y + h):
        pixels[(row * width + x) * 3 : (row * width + x + w) * 3] = bytes(color) * w


def save(path: Path, width: int, height: int, pixels: bytes | bytearray) -> None:
    path.write_bytes(encode_png(width, height, bytes(pixels), 3))


def diff(ctx: ToolContext, before: str, after: str, **kwargs: Any) -> ToolOutput:
    return run(ImageDiffTool(), ImageDiffInput(before=before, path=after, **kwargs), ctx)


def test_imagediff_finds_nothing_in_identical_images(tmp_path: Path, ctx: ToolContext) -> None:
    pixels = canvas(64, 48)
    paint(pixels, 64, (5, 5, 10, 10), (0, 0, 255))
    save(tmp_path / "a.png", 64, 48, pixels)
    save(tmp_path / "b.png", 64, 48, pixels)

    output = diff(ctx, "a.png", "b.png")

    assert output.content == "a.png: 64x48. b.png: 64x48.\nThe compared pixels are identical."
    assert not output.images


def test_imagediff_finds_a_changed_square(tmp_path: Path, ctx: ToolContext) -> None:
    before = canvas(64, 48)
    after = canvas(64, 48)
    paint(after, 64, (20, 10, 8, 6), (255, 0, 0))
    paint(after, 64, (50, 40, 3, 3), (255, 250, 250))  # too slight to count
    save(tmp_path / "a.png", 64, 48, before)
    save(tmp_path / "b.png", 64, 48, after)

    output = diff(ctx, "a.png", "b.png")

    lines = output.content.splitlines()
    assert lines[1] == (
        "1.6% of the pixels changed (48 of 3,072, by more than 24 in some channel), in 1 region:"
    )
    assert lines[2] == "  x=20 y=10 w=8 h=6  (48 pixels changed, 100.0% of the box)"
    assert "outlined in red" in lines[3]
    picture = decode_png(base64.b64decode(output.images[0].source.data))
    assert (picture.width, picture.height) == (64, 48)
    middle = (13 * 64 + 23) * 4
    assert picture.rgba[middle : middle + 3] == bytes([255, 0, 0])  # tinted: 255//2+128, 0, 0
    corner = 0
    assert picture.rgba[corner : corner + 3] == bytes([142, 142, 142])  # dimmed white

    slight = diff(ctx, "a.png", "b.png", threshold=0)
    assert "in 2 regions:" in slight.content
    assert "  x=50 y=40 w=3 h=3  (9 pixels changed, 100.0% of the box)" in slight.content


def test_imagediff_compares_the_overlap_of_different_sizes(
    tmp_path: Path, ctx: ToolContext
) -> None:
    small = canvas(40, 30)
    large = canvas(80, 50)
    paint(large, 80, (60, 40, 10, 5), (0, 0, 0))  # outside the overlap
    save(tmp_path / "a.png", 40, 30, small)
    save(tmp_path / "b.png", 80, 50, large)
    assert diff(ctx, "a.png", "b.png").content.splitlines() == [
        "a.png: 40x30. b.png: 80x50.",
        "The images differ in size, so only the overlapping 40x30 from the top left is compared.",
        "The compared pixels are identical.",
    ]
    paint(large, 80, (30, 20, 20, 20), (0, 0, 0))  # partly inside it
    save(tmp_path / "b.png", 80, 50, large)
    output = diff(ctx, "a.png", "b.png")
    assert "  x=30 y=20 w=10 h=10  (100 pixels changed, 100.0% of the box)" in output.content
    picture = decode_png(base64.b64decode(output.images[0].source.data))
    assert (picture.width, picture.height) == (80, 50)


def test_imagediff_scales_a_wide_picture_down(tmp_path: Path, ctx: ToolContext) -> None:
    before = canvas(2000, 40)
    after = canvas(2000, 40)
    paint(after, 2000, (1000, 10, 100, 10), (0, 0, 0))
    save(tmp_path / "a.png", 2000, 40, before)
    save(tmp_path / "b.png", 2000, 40, after)
    output = diff(ctx, "a.png", "b.png")
    assert "scaled to 1280x26" in output.content
    picture = decode_png(base64.b64decode(output.images[0].source.data))
    assert (picture.width, picture.height) == (1280, 26)


def filtered_png(width: int, height: int, rgba: bytes, color: int = 6) -> bytes:
    """A PNG whose rows use each of the five filters in turn, to test decoding them."""
    bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    stride = width * bpp
    raw = bytearray()
    previous = bytes(stride)
    for y in range(height):
        line = rgba[y * stride : (y + 1) * stride]
        kind = y % 5
        out = bytearray()
        for i, value in enumerate(line):
            a = line[i - bpp] if i >= bpp else 0
            b = previous[i]
            c = previous[i - bpp] if i >= bpp else 0
            if kind == 0:
                predicted = 0
            elif kind == 1:
                predicted = a
            elif kind == 2:
                predicted = b
            elif kind == 3:
                predicted = (a + b) // 2
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predicted = a if pa <= pb and pa <= pc else b if pb <= pc else c
            out.append((value - predicted) & 255)
        raw += bytes([kind]) + out
        previous = line
    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    extra = b""
    if color == 3:
        extra = chunk(b"PLTE", bytes(range(0, 255, 1))[: 3 * 4] + bytes(3 * 252))
        extra += chunk(b"tRNS", bytes([255, 128]))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + extra
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )


def test_png_decoding_undoes_every_filter_and_color_type() -> None:
    width, height = 13, 10
    rgba = bytes(
        (x * 37 + y * 11 + c * 101) % 256
        for y in range(height)
        for x in range(width)
        for c in range(4)
    )
    assert decode_png(filtered_png(width, height, rgba)).rgba == rgba
    rgb = bytes(v for i, v in enumerate(rgba) if i % 4 != 3)
    assert decode_png(filtered_png(width, height, rgb, color=2)).rgba == rgba[:0] + bytes(
        b for i in range(0, len(rgb), 3) for b in (*rgb[i : i + 3], 255)
    )
    gray = bytes((x * 19 + y * 7) % 256 for y in range(height) for x in range(width))
    expanded = decode_png(filtered_png(width, height, gray, color=0)).rgba
    assert expanded[0::4] == gray and expanded[2::4] == gray and set(expanded[3::4]) == {255}
    gray_alpha = bytes(v for g in gray for v in (g, 255 - g))
    decoded = decode_png(filtered_png(width, height, gray_alpha, color=4)).rgba
    assert decoded[1::4] == gray and decoded[3::4] == bytes(255 - g for g in gray)
    indices = bytes((x + y) % 4 for y in range(height) for x in range(width))
    paletted = decode_png(filtered_png(width, height, indices, color=3)).rgba
    assert paletted[0:4] == bytes([0, 1, 2, 255])
    assert paletted[4:8] == bytes([3, 4, 5, 128])


def test_imagediff_explains_an_interlaced_png_without_ffmpeg(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = bytearray(encode_png(4, 4, bytes(48), 3))
    png[28] = 1  # the interlace byte of the header
    png[29:33] = struct.pack(">I", zlib.crc32(bytes(png[12:29])) & 0xFFFFFFFF)
    (tmp_path / "i.png").write_bytes(bytes(png))
    save(tmp_path / "b.png", 4, 4, bytes(48))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ToolError, match=r"interlaced PNG.*Install ffmpeg"):
        diff(ctx, "i.png", "b.png")
    (tmp_path / "t.txt").write_text("hello")
    with pytest.raises(ToolError, match="isn't a PNG, JPEG, GIF or WebP"):
        diff(ctx, "t.txt", "b.png")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_imagediff_converts_a_jpeg_with_ffmpeg(tmp_path: Path, ctx: ToolContext) -> None:
    before = canvas(64, 48)
    after = canvas(64, 48)
    paint(after, 64, (16, 16, 16, 16), (0, 0, 0))
    save(tmp_path / "a.png", 64, 48, before)
    save(tmp_path / "b.png", 64, 48, after)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "b.png", "-q:v", "2", "b.jpg"], cwd=tmp_path, check=True
    )

    output = diff(ctx, "a.png", "b.jpg")

    assert "a.png: 64x48. b.jpg: 64x48." in output.content
    assert "in 1 region:" in output.content
    region = output.content.splitlines()[2].split()
    x, y = int(region[0][2:]), int(region[1][2:])
    assert 13 <= x <= 16 and 13 <= y <= 16  # JPEG blurs the edges a little
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".zwans-imagediff")]


# -- Browser audit

PAGE = b"""<!doctype html><html><head><script src="/app.js"></script></head><body>
<h1>Store</h1>
<h3>Skipped a level</h3>
<img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='40'/%3E" width="40" height="40">
<button id="dup"></button>
<a href="/x" id="dup"><img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'/%3E" width="20" height="20"></a>
<input placeholder="Email">
<label for="name">Name</label> <input id="name">
<p style="color:#aaa;background:#fff">Faint text</p>
<p style="color:#000">Plain text</p>
<div tabindex="3">Focus me</div>
<img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20'/%3E" alt="">
</body></html>"""
SCRIPT = b"window.loaded = true;\n" + b"// padding\n" * 4000


@pytest.fixture
def audit_site() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body, kind = (
                (SCRIPT, "text/javascript") if self.path == "/app.js" else (PAGE, "text/html")
            )
            self.send_response(200)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.mark.skipif(not browser_available(), reason="needs playwright")
def test_the_browser_audits_a_page(audit_site: str, ctx: ToolContext) -> None:
    tool = BrowserTool()

    async def session() -> ToolOutput:
        try:
            with pytest.raises(ToolError, match="Nothing is open yet"):
                await tool.run(BrowserInput(action="audit"), ctx)
            await tool.run(BrowserInput(action="open", url=audit_site), ctx)
            assert tool.host({"action": "audit"}) == "127.0.0.1"
            return await tool.run(BrowserInput(action="audit"), ctx)
        finally:
            await tool.aclose()

    text = asyncio.run(session()).content
    lines = text.splitlines()
    assert lines[0] == f"Audit of (no title) — {audit_site}"
    assert lines[2] == "Accessibility: 11 problems in 9 of 9 checks."
    for line in [
        "- Images without alt text: 2",
        "- Buttons and links with no accessible name: 2",
        '    <input> (placeholder "Email" only) [e3]',
        "- Page language missing: 1",
        "    <html> has no lang attribute",
        "- Page title missing: 1",
        '    <h3> "Skipped a level" comes after an h1',
        '    id "dup" is used 2 times',
        "- Text with low contrast: 1",
        '    <p> "Faint text" 2.32:1 (#aaaaaa on #ffffff), needs 4.5:1',
        "    <div> tabindex=3",
    ]:
        assert line in lines, line
    assert "    <button#dup> [e1]" in lines
    assert '    <a#dup href="/x"> [e2]' in lines
    performance = text[text.index("Performance") :]
    assert "time to first byte" in performance and "load " in performance
    assert "Cumulative layout shift 0.000" in performance
    assert "2 requests" in performance
    assert "script" in performance and f"{audit_site}app.js" in performance
