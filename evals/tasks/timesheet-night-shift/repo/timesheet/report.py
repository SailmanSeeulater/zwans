"""A plain-text weekly report."""

from timesheet.entries import Entry
from timesheet.summary import minutes_by_project, minutes_by_week, overtime_by_week


def hours(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


def weekly_report(entries: list[Entry]) -> str:
    lines = ["Projects"]
    for project, total in minutes_by_project(entries).items():
        lines.append(f"  {project:<12} {hours(total):>6}")
    lines.append("Weeks")
    overtime = overtime_by_week(entries)
    for week, total in minutes_by_week(entries).items():
        line = f"  {week.isoformat()}   {hours(total):>6}"
        if overtime[week]:
            line += f"  (overtime {hours(overtime[week])})"
        lines.append(line)
    return "\n".join(lines)
