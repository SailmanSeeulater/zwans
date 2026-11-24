"""The Chart tool: numbers drawn as a chart in the conversation.

The model gives rows of data, inline or as a CSV or JSON file in the workspace, and says
which field runs along the bottom and which are plotted. Zwans checks them and sends them
to the web UI, which draws the chart in an MCP Apps view (mcp/apps.py) under the call: bars,
lines, areas or points, with a legend, a hover readout and a table of the same numbers.
The model gets a summary of what was drawn, as text: it can't see the picture, and the
terminal shows the same summary.

One chart has one value axis. Series of very different sizes on it make the small ones
flat, so the summary says when that happens rather than adding a second axis.
"""

import csv
import functools
import io
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from zwans.tools.base import ToolContext, ToolError, ToolOutput

Kind = Literal["bar", "line", "area", "scatter"]

VIEW_URI = "ui://zwans/chart"
MAX_SERIES = 8  # the categorical palette's slots; a ninth is never a made-up color
MAX_SCATTER_SERIES = 3  # where every pair of colors must tell apart, only three can
MAX_POINTS = 5_000  # per series
MAX_BARS = 60  # categories; more is a line, or needs grouping
MAX_FILE_BYTES = 20_000_000
SPARK = "▁▂▃▄▅▆▇█"
CURRENCIES = ("$", "€", "£", "¥")


class ChartInput(BaseModel):
    x: str = Field(description="The field that runs along the bottom: dates, numbers or names.")
    y: list[str] = Field(
        description="The field or fields to plot, each its own series on one shared axis. "
        "With `series`, exactly one: the field holding the values."
    )
    data: list[dict[str, Any]] = Field(
        default_factory=list,
        description='The rows, as objects: [{"day": "2026-03-01", "signups": 12}, ...]. '
        "Leave it empty to read `path` instead.",
    )
    path: str = Field(
        default="",
        description="A CSV, TSV, JSON (an array of objects) or JSON Lines file in the "
        "workspace to read the rows from, instead of `data`.",
    )
    series: str = Field(
        default="",
        description="For long data, the field naming each row's series (one row per x and "
        "series): its values become the series, and `y` names the values.",
    )
    kind: Kind | None = Field(
        default=None,
        description="bar for comparing categories, line for change over time, area for a "
        "total over time (with stacked, its parts), scatter for how two numbers relate. "
        "Left out: line for dates and numbers along the bottom, bar for names.",
    )
    title: str = Field(default="", description="What the chart shows, in a few words.")
    subtitle: str = Field(default="", description="A line under the title: units, source.")
    unit: str = Field(
        default="", description='The values\' unit, as "%", "ms" or "$" (put before).'
    )
    stacked: bool = Field(default=False, description="Stack bars or areas into totals.")
    horizontal: bool | None = Field(
        default=None,
        description="Bars across instead of up; left out, long names lay them across.",
    )

    @field_validator("y", mode="before")
    @classmethod
    def _one_or_more(cls, value: Any) -> Any:
        return [value] if isinstance(value, str) else value


class ChartTool:
    name = "Chart"
    description = (
        "Draw numbers as a chart the user sees in the conversation (in the web UI): bars to "
        "compare categories, lines or areas for change over time, points for how two "
        "numbers relate. Give rows of data, or a CSV or JSON file, and say which field is "
        "x and which are plotted. The user can hover for values and open a table of them. "
        "Use it when a picture says it faster than a table: trends, comparisons, outliers. "
        "You get back a text summary of what was drawn."
    )
    input_model = ChartInput
    read_only = True

    async def run(self, args: ChartInput, ctx: ToolContext) -> ToolOutput:
        rows = args.data or (await _read_rows(args.path, ctx) if args.path else [])
        if not rows:
            raise ToolError("There's nothing to chart: give the rows in data, or a file in path.")
        spec = build(args, rows)
        summary = describe(spec)
        arguments = args.model_dump(exclude={"data"}, exclude_defaults=True)
        app: dict[str, Any] = {
            "server": "zwans",
            "tool": {"name": self.name, "title": "Chart", "description": self.description},
            "arguments": arguments,
            "result": {
                "content": [{"type": "text", "text": summary}],
                "structuredContent": spec,
            },
            "uri": VIEW_URI,
            "html": view_html(),
            "csp": {},
            "permissions": [],
            "prefers_border": None,
        }
        return ToolOutput(content=summary, app=app)


@functools.cache
def view_html() -> str:
    return (Path(__file__).parent / "chart_view.html").read_text(encoding="utf-8")


# -- reading a file


async def _read_rows(path: str, ctx: ToolContext) -> list[dict[str, Any]]:
    data = await ctx.executor.read_bytes(path)
    if len(data) > MAX_FILE_BYTES:
        raise ToolError(
            f"{path} is {len(data) / 1e6:.0f} MB; chart a summary of it instead "
            "(group it with Python or SQL first)."
        )
    text = data.decode("utf-8-sig", "replace")
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            found = json.loads(text)
        except json.JSONDecodeError:
            return _json_lines(text, path)
        if isinstance(found, dict):  # {"rows": [...]}: the first list of objects in it
            found = next((v for v in found.values() if isinstance(v, list)), [])
        if not isinstance(found, list) or not all(isinstance(r, dict) for r in found):
            raise ToolError(f"{path} isn't an array of objects, so it has no rows to chart.")
        return found
    try:
        dialect: Any = csv.Sniffer().sniff(text[:20_000], delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel_tab if path.endswith((".tsv", ".tab")) else csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def _json_lines(text: str, path: str) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ToolError(f"{path} line {number} isn't JSON: {exc.msg}.") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


# -- checking the data and laying it out for the view


def build(args: ChartInput, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What the view draws: the x values, each series' values (None for a gap), and how."""
    fields = list(dict.fromkeys(key for row in rows[:1000] for key in row))
    for name in [args.x, *args.y, *([args.series] if args.series else [])]:
        if name not in fields:
            raise ToolError(f"There's no field {name!r}; the rows have {', '.join(fields)}.")
    if not args.y:
        raise ToolError("Name at least one field to plot in y.")
    if args.series and len(args.y) != 1:
        raise ToolError("With series, y names the one field that holds the values.")

    xs_raw: list[Any] = list(dict.fromkeys(_key(row.get(args.x)) for row in rows))
    x_type = _x_type(xs_raw)
    kind: Kind = args.kind or ("bar" if x_type == "category" else "line")
    if kind == "scatter" and x_type == "category":
        raise ToolError(f"A scatter needs numbers along the bottom, and {args.x} has names.")

    # Each value as (series, x, value): long data names its series in a field, wide data
    # has a field per series.
    if args.series:
        names = list(dict.fromkeys(str(row.get(args.series)) for row in rows))
        cells = (
            (str(row.get(args.series)), row.get(args.x), _number(row.get(args.y[0]), args.y[0]))
            for row in rows
        )
    else:
        names = list(args.y)
        cells = (
            (name, row.get(args.x), _number(row.get(name), name)) for row in rows for name in names
        )
    values: dict[str, dict[Any, float | None]] = {name: {} for name in names}
    duplicates = False
    for name, raw_x, value in cells:
        x = _key(raw_x)
        if x not in values[name]:
            values[name][x] = value
            continue
        duplicates = True  # the same x again in a series: added together
        if value is not None:
            values[name][x] = (values[name][x] or 0) + value

    cap = MAX_SCATTER_SERIES if kind == "scatter" else MAX_SERIES
    if len(names) > cap:
        raise ToolError(
            f"That's {len(names)} series; a {kind} chart tells at most {cap} apart by color. "
            "Chart the largest few and fold the rest into an Other series, or make several "
            "charts."
        )
    if kind == "bar" and len(xs_raw) > MAX_BARS:
        raise ToolError(
            f"That's {len(xs_raw)} bars, too many to read. Use a line for a long run of "
            f"dates or numbers, or group the {args.x} values into fewer."
        )
    if len(xs_raw) > MAX_POINTS:
        raise ToolError(
            f"That's {len(xs_raw):,} points per series; at most {MAX_POINTS:,}. "
            "Group them (by day, week, bucket) first."
        )

    xs = xs_raw
    if x_type != "category" and kind != "bar":
        xs = sorted(xs_raw, key=lambda x: _sort_key(x, x_type))
    columns = {name: [values[name].get(x) for x in xs] for name in names}
    stacking = args.stacked and kind in ("bar", "area")
    if stacking and any(v is not None and v < 0 for col in columns.values() for v in col):
        raise ToolError("Stacked bars and areas need values of 0 or more.")
    horizontal = args.horizontal
    if horizontal is None:
        horizontal = kind == "bar" and (
            max((len(str(x)) for x in xs), default=0) > 12 or len(xs) > 16
        )
    return {
        "kind": kind,
        "title": args.title.strip(),
        "subtitle": args.subtitle.strip(),
        "unit": args.unit.strip(),
        "stacked": bool(args.stacked and kind in ("bar", "area")),
        "horizontal": bool(horizontal and kind == "bar"),
        "x": {"name": args.x, "type": x_type, "values": [_shown(x, x_type) for x in xs]},
        "series": [
            {"name": name, "values": [_tidy(v) for v in column]} for name, column in columns.items()
        ],
        "duplicates": duplicates,
    }


def _tidy(value: float | None) -> float | None:
    """Without the float noise of adding (0.1 + 0.2 is 0.30000000000000004)."""
    return None if value is None else float(f"{value:.12g}")


def _key(value: Any) -> Any:
    """A row's x as a key: numbers and dates as they are, everything else as text."""
    if isinstance(value, bool) or value is None:
        return str(value)
    if isinstance(value, (int, float, date)):
        return value
    return str(value).strip()


def _x_type(xs: list[Any]) -> str:
    if xs and all(_as_float(x) is not None for x in xs):
        return "number"
    if xs and all(_as_time(x) is not None for x in xs):
        return "time"
    return "category"


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip().replace(",", "").replace("_", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _as_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if len(text) < 7 or not text[:4].isdigit():
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:  # a month: 2026-03
        return datetime.strptime(text, "%Y-%m")
    except ValueError:
        return None


def _sort_key(x: Any, x_type: str) -> float:
    if x_type == "number":
        return _as_float(x) or 0.0
    found = _as_time(x)
    if found is None:
        return 0.0
    return (found if found.tzinfo else found.replace(tzinfo=UTC)).timestamp()


def _shown(x: Any, x_type: str) -> Any:
    """An x value as the view gets it: a number, an ISO time, or a name."""
    if x_type == "number":
        return _as_float(x)
    if x_type == "time":
        found = _as_time(x)
        if found is None:
            return str(x)
        if isinstance(x, str) and len(x.strip()) == 7:
            return x.strip()  # a month stays a month
        if found.time() == datetime.min.time() and found.tzinfo is None:
            return found.date().isoformat()
        return found.isoformat()
    return str(x)


def _number(value: Any, field: str) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%").lstrip("$€£¥")
        number = _as_float(text)
    else:
        number = _as_float(value)
    if number is None:
        if isinstance(value, str) and value.strip().lower() in ("nan", "null", "none", "n/a", "-"):
            return None
        raise ToolError(f"{field} has {value!r}, which isn't a number; plot a field of numbers.")
    return number


# -- what the model reads


def describe(spec: dict[str, Any]) -> str:
    x, series, kind = spec["x"], spec["series"], spec["kind"]
    xs = x["values"]
    what = f"a {'stacked ' if spec['stacked'] else ''}{kind} chart"
    of = ", ".join(s["name"] for s in series)
    span = f"{len(xs):,} {'points' if kind != 'bar' else 'bars'}"
    if x["type"] != "category" and xs:
        span += f", {x['name']} from {_fmt_x(xs[0])} to {_fmt_x(xs[-1])}"
    title = f' "{spec["title"]}"' if spec["title"] else ""
    lines = [f"Charted{title}: {what} of {of} by {x['name']} ({span})."]
    unit = spec["unit"]
    peaks = []
    for s in series:
        known = [(v, xs[i]) for i, v in enumerate(s["values"]) if v is not None]
        if not known:
            lines.append(f"- {s['name']}: no values")
            continue
        low = min(known, key=lambda p: p[0])
        high = max(known, key=lambda p: p[0])
        peaks.append(max(abs(low[0]), abs(high[0])))
        last = known[-1][0]
        gaps = len(s["values"]) - len(known)
        detail = (
            f"min {_fmt(low[0], unit)} ({_fmt_x(low[1])}), max {_fmt(high[0], unit)} "
            f"({_fmt_x(high[1])}), last {_fmt(last, unit)}"
        )
        if gaps:
            detail += f", {gaps} missing"
        lines.append(f"- {s['name']}: {detail}  {_spark(s['values'])}")
    if len(peaks) > 1 and min(peaks) > 0 and max(peaks) / min(peaks) > 50:
        lines.append(
            "The series share one axis and differ by more than 50 times, so the smaller "
            "ones look flat. Chart them separately, or index each to 100 at its start."
        )
    if spec["duplicates"]:
        lines.append(f"Some {x['name']} values came more than once; their values were added.")
    lines.append("The user sees it as an interactive chart, with a table of the numbers.")
    return "\n".join(lines)


def _fmt(value: float, unit: str = "") -> str:
    text = f"{value:,.0f}" if abs(value) >= 1000 or value == int(value) else f"{value:,.4g}"
    if not unit:
        return text
    if unit in CURRENCIES:
        return f"-{unit}{text[1:]}" if text.startswith("-") else f"{unit}{text}"
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}"


def _fmt_x(value: Any) -> str:
    return _fmt(value) if isinstance(value, float) else str(value)


def _spark(values: list[float | None], width: int = 24) -> str:
    """The shape of a series in a few block characters, for the terminal and the model."""
    known = [v for v in values if v is not None]
    if len(known) < 2:
        return ""
    step = max(1, math.ceil(len(values) / width))
    buckets = [values[i : i + step] for i in range(0, len(values), step)]
    means = [
        sum(b) / len(b) if (b := [v for v in bucket if v is not None]) else None
        for bucket in buckets
    ]
    low, high = min(known), max(known)
    if high == low:
        return SPARK[3] * len(means)
    return "".join(
        " " if m is None else SPARK[round((m - low) / (high - low) * (len(SPARK) - 1))]
        for m in means
    )
