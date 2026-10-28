"""The HTML version of a run's report: one self-contained file to open in a browser."""

from html import escape
from pathlib import Path

from zwans.eval.runner import AttemptResult, Report, Summary

_STYLE = """
:root { --bg: #fff; --fg: #1f2328; --muted: #656d76; --line: #d0d7de; --pass: #1a7f37;
  --fail: #cf222e; --stop: #9a6700; --code: #f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #0d1117; --fg: #e6edf3; --muted: #8d96a0; --line: #30363d; --pass: #3fb950;
    --fail: #f85149; --stop: #d29922; --code: #161b22; }
}
body { background: var(--bg); color: var(--fg); margin: 0 auto; max-width: 1100px;
  padding: 24px 16px; font: 14px/1.5 system-ui, sans-serif; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 32px 0 8px; }
.meta { color: var(--muted); }
.tiles { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
.tile { border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; min-width: 110px; }
.tile b { display: block; font-size: 20px; } .tile span { color: var(--muted); font-size: 12px; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left;
  vertical-align: top; white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.passed { color: var(--pass); font-weight: 600; } .failed { color: var(--fail); font-weight: 600; }
.stopped { color: var(--stop); font-weight: 600; }
pre { background: var(--code); padding: 8px; border-radius: 6px; max-width: 70vw;
  overflow-x: auto; white-space: pre-wrap; font-size: 12px; }
a { color: inherit; }
"""


def render_html(report: Report, out_dir: Path) -> str:
    s = report.summary
    budget = f"${report.budget:.2f}" if report.budget is not None else "none"
    meta = (
        f"{escape(report.agent)} &middot; {escape(report.model)}, effort "
        f"{escape(report.effort)} &middot; started {escape(report.started_at)} &middot; "
        f"{report.repeats} repeats &middot; budget {budget}"
    )
    warning = (
        '<p class="stopped">The budget ran out before every attempt finished.</p>'
        if report.out_of_budget
        else ""
    )
    tiles = "".join(
        f'<div class="tile"><b>{value}</b><span>{label}</span></div>'
        for value, label in [
            (f"{s.pass_rate:.0%}", f"passed ({s.passed}/{s.attempts})"),
            (f"${s.dollars:.2f}", "spent"),
            (f"${s.mean_dollars:.3f}", "mean per attempt"),
            (f"{s.mean_model_calls:.1f}", "model calls"),
            (f"{s.mean_tool_calls:.1f}", "tool calls"),
            (f"{s.tool_error_rate:.0%}", "tool errors"),
            (f"{s.mean_seconds:.0f}s", "mean time"),
        ]
    )
    task_rows = "".join(_task_row(name, summary) for name, summary in report.tasks.items())
    attempt_rows = "".join(_attempt_row(a, out_dir) for a in report.attempts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Eval: {escape(report.config.name)}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>Eval run: {escape(report.config.name)}</h1>
<div class="meta">{meta}</div>
{warning}
<div class="tiles">{tiles}</div>

<h2>Tasks</h2>
<div class="scroll"><table>
<tr><th>Task</th><th class="num">Passed</th><th class="num">Mean $</th>
<th class="num">Model calls</th><th class="num">Tool calls</th><th class="num">Tool errors</th>
<th class="num">Mean time</th></tr>
{task_rows}
</table></div>

<h2>Attempts</h2>
<div class="scroll"><table>
<tr><th>Task</th><th>Result</th><th>Stopped by</th><th class="num">$</th>
<th class="num">Model calls</th><th class="num">Tool calls</th><th class="num">Tool errors</th>
<th class="num">Time</th><th>Transcript</th></tr>
{attempt_rows}
</table></div>
</body>
</html>
"""


def _task_row(name: str, s: Summary) -> str:
    return (
        f"<tr><td>{escape(name)}</td><td class='num'>{s.passed}/{s.attempts}</td>"
        f"<td class='num'>{s.mean_dollars:.3f}</td><td class='num'>{s.mean_model_calls:.1f}</td>"
        f"<td class='num'>{s.mean_tool_calls:.1f}</td>"
        f"<td class='num'>{s.tool_error_rate:.0%}</td>"
        f"<td class='num'>{s.mean_seconds:.0f}s</td></tr>"
    )


def _attempt_row(a: AttemptResult, out_dir: Path) -> str:
    stop = "" if a.stop_reason == "end_turn" else escape(a.stop_reason)
    link = ""
    if a.transcript:
        path = Path(a.transcript)
        href = path.relative_to(out_dir).as_posix() if path.is_relative_to(out_dir) else path
        link = f"<a href='{escape(str(href))}'>{escape(path.name)}</a>"
    row = (
        f"<tr><td>{escape(a.task)} #{a.repeat}</td><td class='{a.status}'>{a.status}</td>"
        f"<td>{stop}</td><td class='num'>{a.dollars:.4f}</td>"
        f"<td class='num'>{a.model_calls}</td><td class='num'>{a.tool_calls}</td>"
        f"<td class='num'>{a.tool_errors}</td><td class='num'>{a.seconds:.1f}s</td>"
        f"<td>{link}</td></tr>"
    )
    details = [*a.errors]
    if a.status == "failed" and a.check_output:
        details.append(f"Check exited {a.check_exit}:\n{a.check_output}")
    if details:
        text = escape("\n\n".join(details))
        row += (
            "<tr><td></td><td colspan='8'><details><summary>Details</summary>"
            f"<pre>{text}</pre></details></td></tr>"
        )
    return row
