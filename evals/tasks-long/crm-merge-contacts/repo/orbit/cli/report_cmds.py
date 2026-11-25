"""orbit report ..."""

from dataclasses import asdict

from orbit.cli.output import emit_json, say
from orbit.reports import (
    activity_report,
    contact_summary,
    pipeline,
    stage_durations,
    top_contacts,
    win_rate,
)
from orbit.reports.activity import render_activity, render_top
from orbit.reports.contacts import render_summary
from orbit.reports.pipeline import render_pipeline


def register(commands) -> None:
    report = commands.add_parser("report", help="reports")
    sub = report.add_subparsers(dest="which", required=True)
    sub.add_parser("contacts").set_defaults(handler=contacts_report)
    pipe = sub.add_parser("pipeline")
    pipe.add_argument("--owner")
    pipe.set_defaults(handler=pipeline_report)
    activity = sub.add_parser("activity")
    activity.add_argument("--since")
    activity.set_defaults(handler=activity)
    top = sub.add_parser("top")
    top.add_argument("--limit", type=int, default=10)
    top.set_defaults(handler=top_report)
    sub.add_parser("stages").set_defaults(handler=stages_report)


def contacts_report(crm, args) -> bool:
    summary = contact_summary(crm)
    if args.json:
        emit_json(asdict(summary))
    else:
        say(render_summary(summary))
    return False


def pipeline_report(crm, args) -> bool:
    rows = pipeline(crm, args.owner)
    if args.json:
        emit_json({"stages": [asdict(row) for row in rows], "win_rate": win_rate(crm)})
    else:
        say(render_pipeline(rows, win_rate(crm)))
    return False


def activity(crm, args) -> bool:
    rows = activity_report(crm, args.since)
    if args.json:
        emit_json([asdict(row) for row in rows])
    else:
        say(render_activity(rows))
    return False


def top_report(crm, args) -> bool:
    rows = top_contacts(crm, args.limit)
    if args.json:
        emit_json([{"id": cid, "name": name, "open_value": value} for cid, name, value in rows])
    else:
        say(render_top(rows))
    return False


def stages_report(crm, args) -> bool:
    durations = stage_durations(crm, crm.clock())
    if args.json:
        emit_json(durations)
    else:
        for stage, days in durations.items():
            say(f"{stage:<12} {days:>7.2f} days")
    return False
