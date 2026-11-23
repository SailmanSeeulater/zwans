"""A session as one HTML file that plays it back, for sharing: open it in any browser, with
no server and nothing to install.

The file holds the session's events from its transcript, trimmed to what a reader follows
(prompts, replies, tool calls and their results, approvals, steering, /loop checks) and
timed as they happened, with long pauses shortened so the replay keeps moving. Before
anything goes in, it's scrubbed: keys and tokens that look like secrets are masked, and
the home folder becomes ~. Thinking isn't included.
"""

import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from zwans import __version__

# Events a reader follows; the rest (usage, model calls, hooks) only feed the totals.
SHOWN = {
    "turn_started",
    "text_delta",
    "tool_call_requested",
    "tool_result",
    "permission_requested",
    "permission_resolved",
    "permission_denied",
    "steered",
    "loop_checked",
    "loop_ended",
    "context_compacted",
    "turn_ended",
    "error",
}
LONGEST_PAUSE = 2.5  # seconds: a longer wait (a slow command, a person reading) is cut to this
BETWEEN_TURNS = 1.2  # and the wait between a turn's end and the next prompt to this
RESULT_CHARS = 6_000  # of each tool result, from its start
MERGE_SECONDS = 0.08  # text arriving closer together than this is one piece

MASK = "•••"
# Things that are secrets on sight: provider keys, cloud keys, chat tokens, bearer tokens.
SECRETS = [
    re.compile(r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
# NAME=value and "name": "value" where the name says it's a secret.
NAMED = re.compile(
    r"""(?ix)
    (\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*["']?\s*[:=]\s*["']?)
    ([^\s"',;]{6,})
    """
)


def scrub(text: str, home: str | None = None) -> str:
    """`text` with what looks like a secret masked, and `home` shortened to ~."""
    for pattern in SECRETS:
        text = pattern.sub(MASK, text)
    text = NAMED.sub(lambda m: m.group(1) + MASK, text)
    if home and len(home) > 1:
        text = text.replace(home, "~")
    return text


def _scrubbed(value: Any, home: str | None) -> Any:
    if isinstance(value, str):
        return scrub(value, home)
    if isinstance(value, list):
        return [_scrubbed(item, home) for item in value]
    if isinstance(value, dict):
        return {key: _scrubbed(item, home) for key, item in value.items()}
    return value


def _when(record: dict[str, Any]) -> float | None:
    try:
        return datetime.fromisoformat(str(record["time"])).timestamp()
    except (KeyError, ValueError):
        return None


def frames(events: list[dict[str, Any]], home: str | None = None) -> list[dict[str, Any]]:
    """The events to play, each with `t`: seconds into the replay, pauses shortened. Text
    arriving in a burst is joined, each turn's end carries what it cost, and every string
    is scrubbed."""
    out: list[dict[str, Any]] = []
    clock = 0.0
    last: float | None = None
    spent = 0.0
    turn_spent = 0.0
    for record in events:
        kind = record.get("type")
        if kind == "model_call" and isinstance(record.get("dollars"), (int, float)):
            spent += float(record["dollars"])
            turn_spent += float(record["dollars"])
        if kind not in SHOWN:
            continue
        when = _when(record)
        if when is not None and last is not None:
            gap = max(0.0, when - last)
            limit = BETWEEN_TURNS if kind == "turn_started" else LONGEST_PAUSE
            clock += min(gap, limit)
        if when is not None:
            last = when
        frame = {k: v for k, v in record.items() if k not in ("time", "untrusted")}
        frame["t"] = round(clock, 3)
        if kind == "turn_started":
            turn_spent = 0.0
        elif kind == "tool_result":
            content = str(frame.get("content") or "")
            if len(content) > RESULT_CHARS:
                cut = len(content) - RESULT_CHARS
                frame["content"] = content[:RESULT_CHARS] + f"\n… {cut:,} more characters"
        elif kind == "turn_ended":
            frame["dollars"] = round(turn_spent, 6)
            frame["total"] = round(spent, 6)
        elif kind == "text_delta" and out:
            previous = out[-1]
            if previous.get("type") == "text_delta" and frame["t"] - previous["t"] < MERGE_SECONDS:
                previous["text"] = str(previous.get("text", "")) + str(frame.get("text", ""))
                continue
        out.append(_scrubbed(frame, home))
    return out


def build(
    events: list[dict[str, Any]],
    *,
    title: str,
    model: str,
    workspace: str,
    created_at: str,
    home: str | None = None,
) -> str:
    """The replay page for a session's events."""
    played = frames(events, home)
    meta = {
        "title": scrub(title, home) or "A Zwans session",
        "model": model,
        "folder": Path(workspace).name if workspace else "",
        "created_at": created_at,
        "version": __version__,
        "turns": sum(1 for f in played if f.get("type") == "turn_started"),
        "dollars": max((float(f.get("total") or 0) for f in played), default=0.0),
        "duration": played[-1]["t"] if played else 0,
    }
    data = json.dumps({"meta": meta, "frames": played}, ensure_ascii=False)
    # Inside a <script>, "</" could end it early, and U+2028/9 break older parsers.
    data = data.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    page_title = escape(str(meta["title"]))
    return PAGE.replace("{{TITLE}}", page_title).replace("{{DATA}}", data)


def filename(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id) or "session"
    return f"zwans-replay-{safe}.html"


PAGE = (Path(__file__).with_name("replay.html")).read_text(encoding="utf-8")
