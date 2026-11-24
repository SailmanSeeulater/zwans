"""Files Read shows in a form a model can use: a PDF as its text, page by page, and a Jupyter
notebook as its cells.

A PDF is binary, so it used to be refused. Its text comes out with pypdf, a page at a time
and a few pages per call; a page with almost no text, as a scan is, comes with the pictures
in it instead, for the model to look at. A notebook is JSON whose source is split into lists
of lines and whose outputs can be pages of base64: shown as cells, numbered for
NotebookEdit, with each output's text cut short and its pictures attached.
"""

import base64
import io
import json
import re
from typing import Any

from zwans.images import ImageError, image_block, media_type
from zwans.messages import ImageBlock
from zwans.tools.base import ToolError, ToolOutput

DEFAULT_PAGES = 20  # pages read when none are asked for
MAX_PDF_CHARS = 60_000  # of text, about 15,000 tokens
SCANNED = 40  # characters of text below which a page is taken for a picture of one
MAX_IMAGES = 5  # pictures sent with one call
MAX_OUTPUT_CHARS = 2_000  # of each notebook output's text


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF-")


def page_range(text: str, count: int) -> range:
    """Pages from "3", "2-5" or "4-", counted from 1, as indexes from 0."""
    match = re.fullmatch(r"\s*(\d+)\s*(?:(-)\s*(\d*)\s*)?", text)
    if not match:
        raise ToolError(f'pages should be a page or a range, as "3" or "2-5", not {text!r}.')
    first = int(match.group(1))
    last = int(match.group(3)) if match.group(3) else (count if match.group(2) else first)
    if not 1 <= first <= count:
        raise ToolError(f"The PDF has {count} page{'s' if count != 1 else ''}.")
    return range(first - 1, min(last, count))


def read_pdf(data: bytes, name: str, pages: str) -> ToolOutput:
    from pypdf import PdfReader  # only when there's a PDF to read
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ToolError(f"{name} is protected with a password.")
        count = len(reader.pages)
    except PdfReadError as exc:
        raise ToolError(f"{name} couldn't be read as a PDF: {exc}") from exc
    if count == 0:
        return ToolOutput(content=f"{name}: a PDF with no pages.")
    wanted = page_range(pages, count) if pages.strip() else range(min(DEFAULT_PAGES, count))
    parts: list[str] = []
    images: list[ImageBlock] = []
    size = 0
    shown_last = wanted.start - 1
    for index in wanted:
        try:
            text = reader.pages[index].extract_text() or ""
        except Exception as exc:  # pypdf raises many kinds for a damaged page
            text = f"(This page's text couldn't be read: {exc})"
        text = re.sub(r"[ \t]+\n", "\n", text).strip()
        part = f"--- Page {index + 1} ---\n{text}"
        if len(text) < SCANNED:
            pictures = _page_images(reader.pages[index], f"{name} page {index + 1}")
            room = MAX_IMAGES - len(images)
            images += pictures[:room]
            if pictures[:room]:
                part += f"\n(The page is mostly a picture: {len(pictures[:room])} attached.)"
            elif not text:
                part += "(No text on this page.)"
        if size + len(part) > MAX_PDF_CHARS and parts:
            break
        parts.append(part)
        size += len(part)
        shown_last = index
    head = f"{name}: a PDF of {count} page{'s' if count != 1 else ''}"
    metadata = reader.metadata
    title = metadata.get("/Title") if metadata is not None else None
    if isinstance(title, str) and title.strip():
        head += f', titled "{title.strip()}"'
    lines = [head + ".", "", "\n\n".join(parts)]
    if shown_last + 1 < count:
        lines.append(
            f"\n(Showing pages {wanted.start + 1}-{shown_last + 1} of {count}. Ask for more with "
            f'pages, as "{shown_last + 2}-{min(shown_last + 1 + DEFAULT_PAGES, count)}".)'
        )
    return ToolOutput(content="\n".join(lines), images=tuple(images))


def _page_images(page: Any, label: str) -> list[ImageBlock]:
    found: list[ImageBlock] = []
    try:
        for picture in page.images:
            data = picture.data
            if media_type(data) is None:
                continue  # a format the API doesn't take, as JPEG 2000 or raw bitmaps
            try:
                found.append(image_block(data, label))
            except ImageError:
                continue  # too big
    except Exception:  # an image pypdf can't decode leaves the page as text only
        return found
    return found


# -- notebooks


def is_notebook(name: str, data: bytes) -> bool:
    return name.endswith(".ipynb") and data.lstrip()[:1] == b"{"


def load_notebook(data: bytes, name: str) -> dict[str, Any]:
    try:
        notebook = json.loads(data)
    except ValueError as exc:
        raise ToolError(f"{name} isn't a valid notebook: {exc}") from exc
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        raise ToolError(f"{name} isn't a notebook: it has no list of cells.")
    return notebook


def text_of(value: object) -> str:
    """A notebook's text field, which is a string or a list of lines."""
    if isinstance(value, list):
        return "".join(str(part) for part in value)
    return value if isinstance(value, str) else ""


def read_notebook(data: bytes, name: str) -> ToolOutput:
    notebook = load_notebook(data, name)
    cells: list[dict[str, Any]] = notebook["cells"]
    language = notebook.get("metadata", {}).get("kernelspec", {}).get("language") or "python"
    parts = [f"{name}: a notebook of {len(cells)} cells, in {language}."]
    images: list[ImageBlock] = []
    for index, cell in enumerate(cells):
        kind = cell.get("cell_type", "code")
        cell_id = f", id {cell['id']}" if cell.get("id") else ""
        count = cell.get("execution_count")
        ran = f", run {count}" if kind == "code" and count else ""
        parts.append(f"\n[cell {index}: {kind}{cell_id}{ran}]\n{text_of(cell.get('source'))}")
        for output in cell.get("outputs") or []:
            shown, picture = _output(output, f"{name} cell {index}")
            if shown:
                parts.append(f"[output]\n{shown}")
            if picture is not None and len(images) < MAX_IMAGES:
                images.append(picture)
                parts.append("[output: a picture, attached]")
    return ToolOutput(content="\n".join(parts), images=tuple(images))


def _output(output: dict[str, Any], label: str) -> tuple[str, ImageBlock | None]:
    kind = output.get("output_type")
    if kind == "stream":
        return _cut(text_of(output.get("text"))), None
    if kind == "error":
        trace = "\n".join(_ANSI.sub("", line) for line in output.get("traceback") or [])
        return _cut(trace or f"{output.get('ename')}: {output.get('evalue')}"), None
    bundle = output.get("data") or {}
    picture = None
    for mime in ("image/png", "image/jpeg"):
        if isinstance(bundle.get(mime), str):
            try:
                picture = image_block(base64.b64decode(bundle[mime]), label)
            except (ImageError, ValueError):
                picture = None
            break
    text = text_of(bundle.get("text/plain"))
    if picture is not None and text.startswith("<Figure"):
        text = ""  # matplotlib's stand-in for the picture
    return _cut(text), picture


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _cut(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[... {len(text) - MAX_OUTPUT_CHARS:,} more characters]"
