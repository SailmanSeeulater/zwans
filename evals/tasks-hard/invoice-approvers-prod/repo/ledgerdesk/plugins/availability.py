"""Availability: people who are away cannot act.

`data/absences.json` lists absences as {"user", "from", "until", "reason"}; a user is away
from `from` (inclusive) to `until` (exclusive). Being away does not stop a user's
delegations from working: that is what delegations are for.
"""

import json
from functools import cache
from pathlib import Path

from ledgerdesk.clock import parse_instant
from ledgerdesk.plugins import Plugin, register


@cache
def _absences(path: Path) -> tuple[tuple[str, object, object, str], ...]:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return tuple(
        (
            entry["user"],
            parse_instant(entry["from"]),
            parse_instant(entry["until"]),
            entry.get("reason", ""),
        )
        for entry in raw
    )


@register("availability")
class Availability(Plugin):
    def check(self, ctx, request):
        for user, start, end, reason in _absences(ctx.path("absences")):
            if user == request.user.username and start <= request.at < end:
                return f"away ({reason})" if reason else "away"
        return None
