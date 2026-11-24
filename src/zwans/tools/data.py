"""The Data tool: what a data file holds, without reading all of it.

A model handed a CSV of a hundred thousand rows either reads the first lines with Read and
guesses the rest, or spends its context on rows that all look alike. This reads the whole
file (or the first 100 MB of a bigger one) and summarizes it: how many rows and columns, and
for each column its type, how many values are empty, how many are distinct, the range and
mean of numbers and dates, the most common values of a column with few of them, then the
first rows as a table. It reads CSV and TSV (the delimiter is sniffed), JSON Lines, a JSON
array of objects, Excel .xlsx (parsed here, with no Excel library) and Parquet, which needs
pyarrow, pandas or duckdb in the project's own Python and is read by a small script run
there.
"""

import csv
import io
import json
import re
import shlex
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_BYTES = 100_000_000  # of a bigger file, only the start is read
MAX_STAT_ROWS = 500_000  # rows that feed the column statistics; the rest are only counted
MAX_COLUMNS = 300
MAX_DISTINCT = 10_000  # distinct values counted per column
TOP_DISTINCT = 50  # a text column with at most this many distinct values shows its top 3
LONG_TEXT = 40  # characters: text longer than this has its lengths shown
MAX_CELL = 30  # characters of a cell in the sample table
MAX_TABLE_COLUMNS = 12  # columns in the sample table unless some are chosen
MAX_OUTPUT_CHARS = 12_000
PARQUET_ROWS = 2_000  # rows a Parquet file's script returns for the statistics
PARQUET_TIMEOUT = 120
PARQUET_MARK = "ZWANS-PARQUET "
NULLS = frozenset({"", "na", "n/a", "nan", "null", "none", "nil", "-"})
INTEGER = re.compile(r"[-+]?(?:0|[1-9]\d*)\Z")
NUMBER = re.compile(r"[-+]?(?:(?:0|[1-9]\d*)(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
DATETIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\Z"
)
EXCEL_EPOCH = datetime(1899, 12, 30)
EXCEL_DATE_FORMATS = frozenset({*range(14, 23), *range(27, 37), *range(45, 48), *range(50, 59)})
NUMERIC_KINDS = ("integer", "number")
TEXT_FORMATS = {
    ".csv": "CSV",
    ".tsv": "TSV",
    ".tab": "TSV",
    ".txt": "CSV",
    ".psv": "CSV",
}

# Run with the project's Python: argv is the file and how many rows to return. Prints one
# line, PARQUET_MARK and JSON: the engine, the schema, the row count and the first rows, or
# what went wrong.
PARQUET_SCRIPT = r"""
import json, sys
path, limit = sys.argv[1], int(sys.argv[2])
MARK = "ZWANS-PARQUET "
def out(found):
    text = json.dumps(found, default=str)
    while len(text) > 1_500_000 and len(found.get("rows", [])) > 10:
        found["rows"] = found["rows"][: len(found["rows"]) // 2]
        text = json.dumps(found, default=str)
    print(MARK + text)
    sys.exit(0)
errors = []
try:
    import pyarrow.parquet as pq
    f = pq.ParquetFile(path)
    rows = []
    for batch in f.iter_batches(batch_size=min(limit, 65536)):
        rows.extend(batch.to_pylist())
        if len(rows) >= limit:
            break
    schema = [[field.name, str(field.type)] for field in f.schema_arrow]
    out({"engine": "pyarrow", "schema": schema, "total": f.metadata.num_rows, "rows": rows[:limit]})
except ImportError:
    pass
except Exception as exc:
    errors.append(f"pyarrow: {exc}")
try:
    import pandas as pd
    df = pd.read_parquet(path)
    schema = [[str(name), str(kind)] for name, kind in df.dtypes.items()]
    rows = json.loads(df.head(limit).to_json(orient="records", date_format="iso"))
    out({"engine": "pandas", "schema": schema, "total": len(df), "rows": rows})
except ImportError:
    pass
except Exception as exc:
    errors.append(f"pandas: {exc}")
try:
    import duckdb
    con = duckdb.connect()
    source = "read_parquet('" + path.replace("'", "''") + "')"
    schema = [[r[0], r[1]] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    total = con.execute(f"SELECT count(*) FROM {source}").fetchone()[0]
    cursor = con.execute(f"SELECT * FROM {source} LIMIT {limit}")
    names = [d[0] for d in cursor.description]
    rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    out({"engine": "duckdb", "schema": schema, "total": total, "rows": rows})
except ImportError:
    pass
except Exception as exc:
    errors.append(f"duckdb: {exc}")
out({"error": "; ".join(errors) if errors else "missing"})
"""


class DataInput(BaseModel):
    path: str = Field(
        description="The data file, relative to the workspace root: .csv, .tsv, .jsonl, "
        ".json, .xlsx or .parquet."
    )
    sheet: str = Field(
        default="",
        description="For an Excel file: the sheet, by name or number (1 is the first). Leave "
        "it empty for the first.",
    )
    columns: list[str] = Field(
        default_factory=list,
        description="Only these columns, by name, in the statistics and the sample rows. Leave "
        "it empty for all of them.",
    )
    rows: int = Field(
        default=5, ge=0, le=50, description="How many of the first rows to show (at most 50)."
    )


class DataTool:
    name = "Data"
    description = (
        "Summarize a data file instead of reading it: CSV or TSV, JSON Lines, a JSON array of "
        "records, Excel .xlsx or Parquet. You get the row and column counts, then for each "
        "column its type, how many values are empty and distinct, the min, max and mean of "
        "numbers and dates and the most common values of text with few of them, then the "
        "first rows as a table. Use columns to focus on some, and sheet to pick an Excel "
        "sheet. Use it before writing code that reads the file, so the code fits the data."
    )
    input_model = DataInput
    read_only = True

    async def run(self, args: DataInput, ctx: ToolContext) -> ToolOutput:
        path = args.path
        suffix = Path(path).suffix.lower()
        focus = [c for c in args.columns if c.strip()]
        if suffix in (".parquet", ".pq"):
            return ToolOutput(content=await _parquet(path, focus, args.rows, ctx))
        data, total_size = await _read(path, ctx)
        if not data:
            raise ToolError(f"{path} is empty.")
        cut = total_size is not None and total_size > len(data)
        summary = Summary(focus, args.rows)
        if data.startswith(b"PAR1"):
            return ToolOutput(content=await _parquet(path, focus, args.rows, ctx))
        if data.startswith(b"PK\x03\x04") or suffix in (".xlsx", ".xlsm"):
            if cut:
                raise ToolError(f"{path} is over {MAX_BYTES // 1_000_000} MB, too big to open.")
            head, names = _xlsx(data, args.sheet, summary)
            note = "Sheets: " + ", ".join(
                f"{name} (shown)" if name == names[1] else name for name in names[0]
            )
            return ToolOutput(content=summary.report(path, head, [note]))
        if args.sheet:
            raise ToolError("sheet is only for Excel files.")
        if cut:
            data = data[: data.rfind(b"\n") + 1] or data
        text, encoding_note = _decode(data)
        stripped = text.lstrip()
        notes = [encoding_note] if encoding_note else []
        if cut:
            notes.append(
                f"Only the first {MAX_BYTES // 1_000_000} MB of the file "
                f"({total_size or 0:,} bytes) were read; counts are of those rows."
            )
        if suffix in (".jsonl", ".ndjson") or (
            suffix != ".json" and stripped.startswith("{") and _is_json_lines(stripped)
        ):
            head = _json_lines(text, summary)
        elif suffix == ".json" or stripped.startswith(("[", "{")):
            head = _json(text, summary, path, cut)
        else:
            head = _delimited(text, suffix, summary)
        return ToolOutput(content=summary.report(path, head, notes))


# -- Reading


async def _read(path: str, ctx: ToolContext) -> tuple[bytes, int | None]:
    """The file's bytes, or the first MAX_BYTES of a bigger one, and its size when known."""
    executor = ctx.executor
    root = getattr(executor, "root", None)
    size: int | None = None
    if isinstance(root, Path):
        try:
            local = root / executor.relative(path)
            size = local.stat().st_size
        except (OSError, ValueError):
            size = None
        if size is not None and size > MAX_BYTES:
            with local.open("rb") as handle:
                return handle.read(MAX_BYTES), size
    try:
        return await executor.read_bytes(path), size
    except IsADirectoryError:
        raise ToolError(f"{path} is a folder, not a data file.") from None


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data[: len(data) // 2 * 2].decode("utf-16", "replace"), ""
    try:
        return data.decode("utf-8-sig"), ""
    except UnicodeDecodeError:
        note = "The file isn't UTF-8; it was read as Windows-1252."
        return data.decode("cp1252", "replace"), note


def _is_json_lines(text: str) -> bool:
    first = text.split("\n", 1)[0].strip()
    try:
        return isinstance(json.loads(first), dict) and "\n" in text.strip()
    except ValueError:
        return False


def _delimited(text: str, suffix: str, summary: "Summary") -> str:
    sample = text[:65_536]
    first_line = sample.split("\n", 1)[0]
    if suffix in (".tsv", ".tab"):
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except csv.Error:
            delimiter = ""
        if not delimiter or delimiter not in first_line:
            counts = {d: first_line.count(d) for d in (",", "\t", ";", "|")}
            delimiter = max(counts, key=lambda d: counts[d]) if any(counts.values()) else ","
    csv.field_size_limit(MAX_BYTES)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        has_header = summary.feed_rows((row for row in reader if row), delimited=True)
    except csv.Error as exc:
        raise ToolError(f"The file couldn't be read as delimited text: {exc}") from exc
    name = {",": "comma", "\t": "tab", ";": "semicolon", "|": "pipe"}.get(delimiter, delimiter)
    kind = "TSV" if delimiter == "\t" else TEXT_FORMATS.get(suffix, "CSV")
    header = "the first row is the header" if has_header else "no header row, columns numbered"
    return f"{kind} ({name}-separated, {header})"


def _json_lines(text: str, summary: "Summary") -> str:
    bad = 0
    first_bad = 0

    def records() -> Iterator[dict[str, Any]]:
        nonlocal bad, first_bad
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                bad += 1
                first_bad = first_bad or number
                continue
            yield value if isinstance(value, dict) else {"value": value}

    summary.feed_records(records())
    head = "JSON Lines"
    if bad:
        which = "1 line isn't" if bad == 1 else f"{bad:,} lines aren't"
        head += f" ({which} JSON, the first at line {first_bad:,})"
    return head


def _json(text: str, summary: "Summary", path: str, cut: bool) -> str:
    if cut:
        raise ToolError(
            f"{path} is over {MAX_BYTES // 1_000_000} MB, too big to read as one JSON value."
        )
    try:
        value = json.loads(text)
    except ValueError as exc:
        if _is_json_lines(text.lstrip()):
            return _json_lines(text, summary)
        raise ToolError(f"{path} isn't valid JSON: {exc}") from exc
    where = ""
    if isinstance(value, dict):
        lists = [(k, v) for k, v in value.items() if isinstance(v, list) and v]
        if not lists:
            raise ToolError(
                f"{path} holds a JSON object with no list of records in it; use Read for it."
            )
        key, value = max(lists, key=lambda kv: len(kv[1]))
        where = f' under "{key}"'
    if not isinstance(value, list):
        raise ToolError(f"{path} holds a single JSON value, not records; use Read for it.")
    summary.feed_records(v if isinstance(v, dict) else {"value": v} for v in value)
    return f"a JSON array of records{where}"


# -- Excel


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(element: ElementTree.Element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return None


def _text_of(element: ElementTree.Element) -> str:
    """The text of a shared or inline string: its <t> runs, without phonetic hints."""
    parts: list[str] = []
    for child in element:
        tag = _local(child.tag)
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _column_index(ref: str) -> int:
    index = 0
    for char in ref:
        if not char.isalpha():
            break
        index = index * 26 + ord(char.upper()) - 64
    return index - 1


def _xlsx(data: bytes, wanted: str, summary: "Summary") -> tuple[str, tuple[list[str], str]]:
    try:
        book = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ToolError(f"The file isn't a valid .xlsx (zip) file: {exc}") from exc
    names = set(book.namelist())
    if "xl/workbook.xml" not in names:
        raise ToolError("The zip file isn't an Excel workbook (it has no xl/workbook.xml).")
    try:
        workbook = ElementTree.fromstring(book.read("xl/workbook.xml"))
        sheets = [
            (s.get("name") or "?", _attr(s, "id") or "")
            for s in workbook.iter()
            if _local(s.tag) == "sheet"
        ]
        targets: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            for rel in ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels")):
                target = rel.get("Target") or ""
                target = target.lstrip("/") if target.startswith("/") else "xl/" + target
                targets[rel.get("Id") or ""] = target
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
            shared = [_text_of(si) for si in root if _local(si.tag) == "si"]
        dates = _date_styles(book.read("xl/styles.xml")) if "xl/styles.xml" in names else {}
    except ElementTree.ParseError as exc:
        raise ToolError(f"The workbook's XML couldn't be read: {exc}") from exc
    if not sheets:
        raise ToolError("The workbook has no sheets.")
    sheet_names = [name for name, _ in sheets]
    chosen = 0
    if wanted.strip():
        lowered = [n.lower() for n in sheet_names]
        if wanted.strip().lower() in lowered:
            chosen = lowered.index(wanted.strip().lower())
        elif wanted.strip().isdigit() and 1 <= int(wanted) <= len(sheets):
            chosen = int(wanted) - 1
        else:
            raise ToolError(f"There's no sheet {wanted!r}. Sheets: {', '.join(sheet_names)}.")
    name, rel_id = sheets[chosen]
    part = targets.get(rel_id) or f"xl/worksheets/sheet{chosen + 1}.xml"
    if part not in names:
        raise ToolError(f"The workbook names sheet {name!r}, but its part {part} is missing.")
    with book.open(part) as stream:
        try:
            summary.feed_rows(_sheet_rows(stream, shared, dates))
        except ElementTree.ParseError as exc:
            raise ToolError(f"Sheet {name!r} couldn't be read: {exc}") from exc
    return "Excel workbook", (sheet_names, name)


def _date_styles(styles_xml: bytes) -> dict[int, str]:
    """Which cell styles show a number as a date: style index -> "date", "datetime" or
    "time"."""
    root = ElementTree.fromstring(styles_xml)
    custom: dict[int, str] = {}
    xfs: list[int] = []
    for element in root:
        tag = _local(element.tag)
        if tag == "numFmts":
            for fmt in element:
                custom[int(fmt.get("numFmtId") or 0)] = fmt.get("formatCode") or ""
        elif tag == "cellXfs":
            xfs = [int(xf.get("numFmtId") or 0) for xf in element if _local(xf.tag) == "xf"]
    kinds: dict[int, str] = {}
    for index, fmt_id in enumerate(xfs):
        kind = ""
        if fmt_id in custom:
            kind = _date_kind(custom[fmt_id])
        elif fmt_id in EXCEL_DATE_FORMATS:
            kind = "time" if fmt_id in (18, 19, 20, 21, 45, 46, 47) else "date"
            kind = "datetime" if fmt_id == 22 else kind
        if kind:
            kinds[index] = kind
    return kinds


def _date_kind(code: str) -> str:
    bare = re.sub(r'"[^"]*"|\\.|\[[^\]]*\]', "", code).lower().replace("general", "")
    has_date = bool(re.search(r"[yd]", bare))
    has_time = bool(re.search(r"[hs]", bare))
    if has_date:
        return "datetime" if has_time else "date"
    return "time" if has_time else ""


def _sheet_rows(stream: Any, shared: list[str], dates: dict[int, str]) -> Iterator[list[Any]]:
    row: list[Any] = []
    for _, element in ElementTree.iterparse(stream, events=("end",)):
        tag = _local(element.tag)
        if tag == "c":
            ref = element.get("r")
            index = _column_index(ref) if ref else len(row)
            if index >= MAX_COLUMNS * 4:
                element.clear()
                continue
            value = _cell(element, shared, dates)
            if index >= len(row):
                row.extend([None] * (index - len(row) + 1))
            row[index] = value
            element.clear()
        elif tag == "row":
            yield row
            row = []
            element.clear()


def _cell(element: ElementTree.Element, shared: list[str], dates: dict[int, str]) -> Any:
    kind = element.get("t") or "n"
    raw: str | None = None
    for child in element:
        tag = _local(child.tag)
        if tag == "v":
            raw = child.text
        elif tag == "is":
            return _text_of(child)
    if raw is None:
        return None
    if kind == "s":
        index = int(raw)
        return shared[index] if 0 <= index < len(shared) else None
    if kind == "b":
        return raw.strip() == "1"
    if kind in ("str", "e", "d"):
        return raw
    try:
        number = float(raw)
    except ValueError:
        return raw
    style = dates.get(int(element.get("s") or 0))
    if style:
        moment = EXCEL_EPOCH + timedelta(days=number)
        if style == "date":
            return moment.date().isoformat()
        if style == "time":
            return moment.strftime("%H:%M:%S")
        return moment.isoformat(sep=" ", timespec="seconds")
    return int(number) if number.is_integer() and abs(number) < 2**53 else number


# -- Parquet


async def _parquet(path: str, focus: list[str], sample: int, ctx: ToolContext) -> str:
    target = ctx.executor.relative(path)
    script = shlex.quote(PARQUET_SCRIPT)
    command = (
        "if command -v python >/dev/null 2>&1; then PY=python; else PY=python3; fi; "
        f'"$PY" -I -c {script} {shlex.quote(target)} {PARQUET_ROWS}'
    )
    result = await ctx.executor.run_shell(command, timeout=PARQUET_TIMEOUT)
    if result.timed_out:
        raise ToolError(f"Reading the Parquet file took over {PARQUET_TIMEOUT}s and was stopped.")
    line = next((ln for ln in result.output.splitlines() if ln.startswith(PARQUET_MARK)), None)
    if line is None:
        detail = result.output.strip()[-1_000:] or f"exit code {result.exit_code}"
        raise ToolError(f"The Parquet file couldn't be read with the project's Python: {detail}")
    try:
        found = json.loads(line[len(PARQUET_MARK) :])
    except ValueError as exc:
        raise ToolError(f"The Parquet reader's output couldn't be parsed: {exc}") from exc
    error = found.get("error")
    if error == "missing":
        raise ToolError(
            "Reading Parquet needs pyarrow, pandas or duckdb in the project's Python, and none "
            "is installed. Install one (pip install pyarrow), or convert the file to CSV."
        )
    if error:
        raise ToolError(f"The Parquet file couldn't be read: {error}")
    schema = {str(name): str(kind) for name, kind in found.get("schema", [])}
    rows = found.get("rows") or []
    total = int(found.get("total") or 0)
    summary = Summary(focus, sample, declared=schema)
    for name in schema:
        summary.column(name)
    summary.feed_records(r for r in rows if isinstance(r, dict))
    notes = []
    if total > summary.rows:
        notes.append(f"Column statistics come from the first {summary.rows:,} rows.")
    summary.total_rows = max(total, summary.rows)
    return summary.report(path, f"Parquet (read with {found.get('engine')})", notes)


# -- Statistics


def classify(value: Any) -> tuple[str, Any]:
    """A value's kind and the value to compare it by, or ("", None) when it's empty."""
    if value is None:
        return "", None
    if isinstance(value, bool):
        return "boolean", value
    if isinstance(value, int):
        return "integer", value
    if isinstance(value, float):
        return ("", None) if value != value else ("number", value)
    if isinstance(value, dict):
        return "object", json.dumps(value, ensure_ascii=False)[:200]
    if isinstance(value, list):
        return "list", json.dumps(value, ensure_ascii=False)[:200]
    text = str(value).strip()
    if text.lower() in NULLS:
        return "", None
    first = text[0]
    if first.isdigit() or first in "+-.":
        if INTEGER.match(text):
            return "integer", int(text)
        if NUMBER.match(text):
            return "number", float(text)
        if DATE.match(text):
            return "date", text
        if DATETIME.match(text):
            return "datetime", text.replace("T", " ")
    elif text.lower() in ("true", "false"):
        return "boolean", text.lower() == "true"
    return "text", text


class Column:
    def __init__(self, name: str) -> None:
        self.name = name
        self.count = 0  # values that aren't empty
        self.kinds: Counter[str] = Counter()
        self.examples: dict[str, str] = {}
        self.values: Counter[Any] = Counter()
        self.overflow = False  # more than MAX_DISTINCT distinct values
        self.low: Any = None
        self.high: Any = None
        self.total = 0.0
        self.numbers = 0
        self.date_low: str | None = None
        self.date_high: str | None = None
        self.short = 1 << 62  # the shortest text
        self.long = 0
        self.length_total = 0

    def add(self, value: Any) -> None:
        kind, key = classify(value)
        if not kind:
            return
        self.count += 1
        self.kinds[kind] += 1
        if kind not in self.examples:
            self.examples[kind] = str(key)[:MAX_CELL]
        if not self.overflow:
            if key in self.values or len(self.values) < MAX_DISTINCT:
                self.values[key] += 1
            else:
                self.overflow = True
        if kind in NUMERIC_KINDS:
            self.numbers += 1
            self.total += key
            if self.low is None or key < self.low:
                self.low = key
            if self.high is None or key > self.high:
                self.high = key
        elif kind in ("date", "datetime"):
            if self.date_low is None or key < self.date_low:
                self.date_low = key
            if self.date_high is None or key > self.date_high:
                self.date_high = key
        elif kind in ("text", "object", "list"):
            size = len(key)
            self.length_total += size
            self.short = min(self.short, size)
            self.long = max(self.long, size)

    def kind(self) -> tuple[str, str]:
        """The column's type, and a note on values that don't fit it."""
        if not self.count:
            return "empty", ""
        kinds = self.kinds
        numeric = kinds["integer"] + kinds["number"]
        dated = kinds["date"] + kinds["datetime"]
        exact = (
            ("integer", kinds["integer"]),
            ("number", numeric),
            ("boolean", kinds["boolean"]),
            ("date", kinds["date"]),
            ("datetime", dated),
            ("object", kinds["object"]),
            ("list", kinds["list"]),
        )
        for kind, fitting in exact:
            if fitting == self.count:
                return kind, ""
        # Mostly numbers or dates, with a few stray values such as "unknown".
        for kind, fitting in (("number", numeric), ("datetime", dated)):
            if fitting >= 0.95 * self.count:
                odd = next(k for k in kinds if k not in _fits(kind))
                others = self.count - fitting
                return kind, f"{others:,} not {kind}, as {self.examples[odd]!r}"
        return "text", ""

    def details(self, kind: str) -> str:
        parts: list[str] = []
        if kind in NUMERIC_KINDS and self.numbers:
            mean = self.total / self.numbers
            parts.append(f"min {_number(self.low)}, max {_number(self.high)}, mean {mean:.6g}")
        elif kind in ("date", "datetime") and self.date_low:
            parts.append(f"from {self.date_low} to {self.date_high}")
        elif kind == "boolean":
            parts.append(f"true {self.values[True]:,}, false {self.values[False]:,}")
        else:
            distinct = len(self.values)
            few = distinct <= TOP_DISTINCT or distinct * 5 <= self.count
            if not self.overflow and few and distinct < self.count:
                top = self.values.most_common(3)
                parts.append("top: " + ", ".join(f"{_clip(str(v), 24)!r} {n:,}" for v, n in top))
            if self.long > LONG_TEXT:
                texts = self.kinds["text"] + self.kinds["object"] + self.kinds["list"]
                mean_length = self.length_total / max(texts, 1)
                parts.append(f"length {self.short}-{self.long}, mean {mean_length:.0f}")
        return "; ".join(parts)


def _fits(kind: str) -> tuple[str, ...]:
    return {
        "integer": ("integer",),
        "number": NUMERIC_KINDS,
        "date": ("date",),
        "datetime": ("date", "datetime"),
    }.get(kind, (kind,))


def _number(value: Any) -> str:
    if isinstance(value, int):
        return f"{value:,}" if abs(value) >= 10_000 else str(value)
    return f"{value:.6g}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Summary:
    """Column statistics, fed one row at a time, and the first rows kept for a table."""

    def __init__(
        self, focus: list[str], sample: int, declared: dict[str, str] | None = None
    ) -> None:
        self.focus = {c.strip().lower(): c for c in focus}
        self.sample_size = sample
        self.declared = declared or {}
        self.columns: dict[str, Column] = {}
        self.names: dict[str, None] = {}  # every column seen, in order
        self.sample: list[dict[str, Any]] = []
        self.rows = 0  # rows that fed the statistics
        self.total_rows = 0  # rows in what was read
        self.ragged = 0  # delimited rows with a different number of fields
        self.dropped_columns = 0

    def column(self, name: str) -> Column | None:
        found = self.columns.get(name)
        if found is not None:
            return found
        if name not in self.names:
            if len(self.names) >= MAX_COLUMNS:
                self.dropped_columns += 1
                return None
            self.names[name] = None
        if self.focus and name.lower() not in self.focus:
            return None
        found = self.columns[name] = Column(name)
        return found

    def feed_records(self, records: Iterable[dict[str, Any]]) -> None:
        for record in records:
            self.total_rows += 1
            if self.rows >= MAX_STAT_ROWS:
                continue
            self.rows += 1
            if len(self.sample) < self.sample_size:
                self.sample.append(record)
            for key, value in record.items():
                column = self.columns.get(key) or self.column(str(key))
                if column is not None:
                    column.add(value)

    def feed_rows(self, rows: Iterable[list[Any]], delimited: bool = False) -> bool:
        """Rows of cells, the first perhaps a header. Returns whether it was taken as one."""
        iterator = iter(rows)
        first = next(iterator, None)
        if first is None:
            return False
        has_header = _looks_like_header(first)
        if has_header:
            header = [str(c).strip() for c in first]
        else:
            header = []
            iterator = _chain(first, iterator)
        width = len(header)
        names = _unique(header)

        def records() -> Iterator[dict[str, Any]]:
            nonlocal names, width
            for row in iterator:
                if delimited and has_header and len(row) != width:
                    self.ragged += 1
                while len(row) > len(names) and (row[-1] is None or row[-1] == ""):
                    row = row[:-1]
                if len(row) > len(names):
                    names = names + [f"column {n + 1}" for n in range(len(names), len(row))]
                yield dict(zip(names, row, strict=False))

        for name in names:
            self.column(name)
        self.feed_records(records())
        return has_header

    def report(self, path: str, head: str, notes: list[str]) -> str:
        missing = [c for key, c in self.focus.items() if key not in {n.lower() for n in self.names}]
        if missing:
            shown = ", ".join(list(self.names)[:40])
            raise ToolError(f"No column named {', '.join(missing)}. The columns: {shown}.")
        count = len(self.names) + self.dropped_columns
        lines = [f"{path}: {head}, {self.total_rows:,} rows x {count:,} columns."]
        lines += notes
        if self.rows < self.total_rows and self.rows == MAX_STAT_ROWS:
            lines.append(f"Column statistics come from the first {self.rows:,} rows.")
        if self.ragged:
            lines.append(f"{self.ragged:,} rows have a different number of fields than the header.")
        if self.dropped_columns:
            lines.append(f"Only the first {MAX_COLUMNS} columns are summarized.")
        columns = list(self.columns.values())
        if self.focus:
            order = {key: n for n, key in enumerate(self.focus)}
            columns.sort(key=lambda c: order.get(c.name.lower(), 0))
        table = []
        for column in columns:
            kind, odd = column.kind()
            declared = self.declared.get(column.name)
            empty = self.rows - column.count
            distinct = f"{MAX_DISTINCT:,}+" if column.overflow else f"{len(column.values):,}"
            details = column.details(kind)
            if odd:
                details = f"{details}; {odd}" if details else odd
            shown_kind = f"{declared} ({kind})" if declared else kind
            table.append([_clip(column.name, 40), shown_kind, f"{empty:,}", distinct, details])
        if table:
            header = ["column", "type", "empty", "distinct", "details"]
            lines += ["", *_table(header, table, [False, False, True, True, False])]
        if self.sample:
            names = [c.name for c in columns]
            cut = len(names) > MAX_TABLE_COLUMNS
            names = names[:MAX_TABLE_COLUMNS]
            cells = [[_cell_text(record.get(n)) for n in names] for record in self.sample]
            label = f"First {len(self.sample)} rows"
            if cut:
                label += f" (the first {MAX_TABLE_COLUMNS} columns; choose others with columns)"
            lines += ["", label + ":", *_table([_clip(n, MAX_CELL) for n in names], cells)]
        text = "\n".join(lines)
        if len(text) > MAX_OUTPUT_CHARS:
            text = (
                text[:MAX_OUTPUT_CHARS].rsplit("\n", 1)[0]
                + "\n[... cut here: name fewer columns with columns, or ask for fewer rows]"
            )
        return text


def _looks_like_header(row: list[Any]) -> bool:
    """A first row of distinct text (some cells may be blank), with no numbers or dates."""
    cells = [c for c in row if c is not None and not (isinstance(c, str) and not c.strip())]
    if not cells:
        return False
    if any(not isinstance(c, str) for c in cells):
        return False
    if any(classify(c)[0] not in ("text", "") for c in cells):
        return False
    stripped = [c.strip() for c in cells]
    return len(set(stripped)) == len(stripped)


def _chain(first: list[Any], rest: Iterator[list[Any]]) -> Iterator[list[Any]]:
    yield first
    yield from rest


def _unique(names: list[str]) -> list[str]:
    seen: Counter[str] = Counter()
    out = []
    for n, name in enumerate(names):
        name = name or f"column {n + 1}"
        seen[name] += 1
        out.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return out


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    elif isinstance(value, bool):
        value = "true" if value else "false"
    return _clip(str(value), MAX_CELL)


def _table(header: list[str], rows: list[list[str]], right: list[bool] | None = None) -> list[str]:
    """An aligned table; numbers are right-aligned unless `right` says per column."""
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    if right is None:
        right = [
            all(classify(r[i])[0] in NUMERIC_KINDS or not r[i] for r in rows)
            and any(r[i] for r in rows)
            for i in range(len(header))
        ]

    def line(cells: list[str]) -> str:
        parts = [
            c.rjust(w) if r else c.ljust(w) for c, w, r in zip(cells, widths, right, strict=True)
        ]
        return "  ".join(parts).rstrip()

    return [line(header), line(["-" * w for w in widths]), *(line(r) for r in rows)]
