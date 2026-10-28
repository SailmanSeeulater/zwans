"""Import posts from the old blog's JSON export.

    {"author": "ada", "posts": [{"date": "2019-05-03", "text": "..."}, ...]}

The old blog only kept dates, so every imported post is timestamped at midnight UTC on
its day. Posts are imported in the order they appear in the export.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from feedsvc.backends import make_backend
from feedsvc.models import MAX_BODY, ValidationError
from feedsvc.service import FeedService


@dataclass
class ImportReport:
    imported: int = 0
    skipped: list[tuple[int, str]] = field(default_factory=list)  # (index, reason)


def midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def import_export(
    service: FeedService, data: dict[str, object], author: str | None = None
) -> ImportReport:
    report = ImportReport()
    who = author or str(data.get("author", ""))
    posts = data.get("posts")
    if not isinstance(posts, list):
        raise ValidationError("the export has no posts list")
    for index, item in enumerate(posts):
        if not isinstance(item, dict):
            report.skipped.append((index, "not an object"))
            continue
        try:
            day = date.fromisoformat(str(item.get("date", "")))
        except ValueError:
            report.skipped.append((index, f"bad date {item.get('date')!r}"))
            continue
        text = str(item.get("text", "")).strip()
        if len(text) > MAX_BODY:
            text = text[: MAX_BODY - 1].rstrip() + "…"
        try:
            service.publish(who, text, at=midnight(day))
        except ValidationError as exc:
            report.skipped.append((index, str(exc)))
            continue
        report.imported += 1
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feedsvc.importer")
    parser.add_argument("export")
    parser.add_argument("--author")
    parser.add_argument("--db", default="feed.db")
    args = parser.parse_args(argv)
    data = json.loads(Path(args.export).read_text(encoding="utf-8"))
    service = FeedService(make_backend("sqlite", args.db))
    report = import_export(service, data, args.author)
    print(f"imported {report.imported}, skipped {len(report.skipped)}")
    for index, reason in report.skipped:
        print(f"  post {index}: {reason}")
    service.backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
