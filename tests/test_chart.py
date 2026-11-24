"""The Chart tool: rows checked and laid out for the web UI's view, and summarized for the
model."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.chart import VIEW_URI, ChartInput, ChartTool, build, describe


def chart(tmp_path: Path, **args: Any) -> ToolOutput:
    ctx = ToolContext(executor=LocalExecutor(tmp_path))
    output: ToolOutput = asyncio.run(ChartTool().run(ChartInput(**args), ctx))
    return output


def spec(**args: Any) -> dict[str, Any]:
    rows = args.pop("data")
    return build(ChartInput(data=rows, **args), rows)


DAYS = [
    {"day": "2026-03-03", "signups": 19, "churn": 2},
    {"day": "2026-03-01", "signups": 12, "churn": 1},
    {"day": "2026-03-02", "signups": "7", "churn": None},
]


def test_dates_make_a_line_in_time_order_with_gaps_kept(tmp_path: Path) -> None:
    out = chart(tmp_path, data=DAYS, x="day", y=["signups", "churn"], title="Signups")
    found = out.app["result"]["structuredContent"] if out.app else {}

    assert found["kind"] == "line"
    assert found["x"] == {
        "name": "day",
        "type": "time",
        "values": ["2026-03-01", "2026-03-02", "2026-03-03"],
    }
    assert found["series"] == [
        {"name": "signups", "values": [12.0, 7.0, 19.0]},
        {"name": "churn", "values": [1.0, None, 2.0]},
    ]
    assert out.content.startswith(
        'Charted "Signups": a line chart of signups, churn by day (3 points, '
        "day from 2026-03-01 to 2026-03-03)."
    )
    assert "- signups: min 7 (2026-03-02), max 19 (2026-03-03), last 19" in out.content
    assert "- churn: min 1 (2026-03-01), max 2 (2026-03-03), last 2, 1 missing" in out.content


def test_the_view_comes_with_the_result_as_an_mcp_app(tmp_path: Path) -> None:
    out = chart(tmp_path, data=DAYS, x="day", y="signups")

    assert out.app is not None
    assert out.app["uri"] == VIEW_URI and out.app["server"] == "zwans"
    assert "ui/initialize" in out.app["html"] and "ui/notifications/tool-result" in out.app["html"]
    assert out.app["csp"] == {} and out.app["permissions"] == []
    # The rows go once, in the result; the arguments the view is told about leave them out.
    assert out.app["arguments"] == {"x": "day", "y": ["signups"]}
    assert out.app["result"]["content"] == [{"type": "text", "text": out.content}]


def test_names_make_bars_and_long_names_lay_them_across() -> None:
    short = spec(data=[{"team": "Web", "bugs": 4}, {"team": "API", "bugs": 9}], x="team", y="bugs")
    long = spec(
        data=[{"team": "Payments and billing", "bugs": 4}, {"team": "API", "bugs": 9}],
        x="team",
        y="bugs",
    )

    assert short["kind"] == "bar" and short["horizontal"] is False
    assert short["x"]["values"] == ["Web", "API"]  # bars keep the order given
    assert long["horizontal"] is True


def test_long_data_becomes_one_series_per_name_and_repeats_are_added() -> None:
    rows = [
        {"month": "2026-01", "region": "EU", "sales": 5},
        {"month": "2026-01", "region": "US", "sales": 8},
        {"month": "2026-02", "region": "EU", "sales": 6},
        {"month": "2026-02", "region": "EU", "sales": 1},
    ]
    found = spec(data=rows, x="month", y="sales", series="region", kind="area", stacked=True)

    assert found["x"]["values"] == ["2026-01", "2026-02"]  # months stay months
    assert found["series"] == [
        {"name": "EU", "values": [5.0, 7.0]},
        {"name": "US", "values": [8.0, None]},
    ]
    assert found["stacked"] is True and found["duplicates"] is True
    assert "came more than once; their values were added" in describe(found)


def test_adding_repeats_leaves_no_float_noise() -> None:
    rows = [{"k": "a", "v": 0.1}, {"k": "a", "v": 0.2}]
    assert spec(data=rows, x="k", y="v")["series"][0]["values"] == [0.3]


def test_series_far_apart_in_size_are_flagged_rather_than_given_a_second_axis() -> None:
    rows = [{"t": n, "requests": 50_000 + n, "errors": n % 3} for n in range(10)]
    text = describe(spec(data=rows, x="t", y=["requests", "errors"]))

    assert "differ by more than 50 times" in text
    assert "requests: min 50,000 (0), max 50,009 (9)" in text


def test_units_and_the_shape_in_block_characters() -> None:
    rows = [{"n": n, "latency": float(n * n)} for n in range(8)]
    text = describe(spec(data=rows, x="n", y="latency", unit="ms"))

    assert "max 49 ms (7)" in text
    assert "last 49 ms  ▁▁▂▂▃▅▆█" in text


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"x": "nope", "y": "signups"}, "There's no field 'nope'; the rows have day, signups"),
        ({"x": "day", "y": ["signups", "churn"], "series": "day"}, "y names the one field"),
        ({"x": "signups", "y": "day"}, "day has '2026-03-03', which isn't a number"),
        ({"x": "day", "y": "signups", "kind": "scatter"}, ""),
    ],
)
def test_what_cant_be_charted_says_why(args: dict[str, Any], message: str) -> None:
    if not message:
        assert spec(data=DAYS, **args)["kind"] == "scatter"  # dates are numbers enough
        return
    with pytest.raises(ToolError, match=message):
        spec(data=DAYS, **args)


def test_limits_keep_a_chart_readable() -> None:
    wide = [{"x": 1, **{f"s{n}": n for n in range(9)}}]
    with pytest.raises(ToolError, match="9 series; a line chart tells at most 8 apart"):
        spec(data=wide, x="x", y=[f"s{n}" for n in range(9)])
    with pytest.raises(ToolError, match="a scatter chart tells at most 3"):
        spec(data=wide, x="x", y=["s0", "s1", "s2", "s3"], kind="scatter")
    with pytest.raises(ToolError, match="A scatter needs numbers along the bottom"):
        spec(data=[{"name": "a", "v": 1}], x="name", y="v", kind="scatter")
    with pytest.raises(ToolError, match="61 bars, too many"):
        spec(data=[{"k": f"k{n}", "v": n} for n in range(61)], x="k", y="v")
    with pytest.raises(ToolError, match="Stacked bars and areas need values of 0 or more"):
        spec(data=[{"k": "a", "v": -1, "w": 2}], x="k", y=["v", "w"], stacked=True)


def test_rows_come_from_a_csv_or_json_file(tmp_path: Path) -> None:
    (tmp_path / "sales.csv").write_text("month;total\n2026-01;1.200\n2026-02;900\n")
    (tmp_path / "runs.json").write_text('{"rows": [{"run": 1, "ms": 30}, {"run": 2, "ms": 25}]}')
    (tmp_path / "runs.jsonl").write_text('{"run": 1, "ms": 30}\n\n{"run": 2, "ms": 28}\n')

    sales = chart(tmp_path, path="sales.csv", x="month", y="total")
    runs = chart(tmp_path, path="runs.json", x="run", y="ms")
    lines = chart(tmp_path, path="runs.jsonl", x="run", y="ms")

    assert sales.app and sales.app["result"]["structuredContent"]["series"][0]["values"] == [
        1.2,
        900.0,
    ]
    assert "a line chart of ms by run (2 points, run from 1 to 2)" in runs.content
    assert "last 28" in lines.content
    with pytest.raises(ToolError, match="nothing to chart"):
        chart(tmp_path, x="a", y="b")


def test_a_read_rule_covers_the_file_it_charts(tmp_path: Path) -> None:
    policy = Policy.default()
    policy.add(PolicyFile(mode="ask", deny=["Read(private/**)"]), "test")
    executor = LocalExecutor(tmp_path)
    permissions = Permissions(policy, lambda path: True, executor.relative, root=executor.root)

    def decide(args: dict[str, Any]) -> Decision:
        return permissions.check(ChartTool(), args).decision

    assert decide({"x": "a", "y": ["b"], "path": "private/pay.csv"}) == Decision.DENY
    assert decide({"x": "a", "y": ["b"], "data": [{"a": 1, "b": 2}]}) == Decision.ALLOW
