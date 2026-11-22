import json
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from zwans import pricing
from zwans.usage import Call, archive, bucket_start, read_calls, summarize


def record(time: str, model: str = "claude-opus-5-5", **tokens: int) -> str:
    return json.dumps({"time": time, "type": "usage_updated", "model": model, **tokens})


def write(home: Path, session: str, *lines: str) -> Path:
    path = home / "transcripts" / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", "utf-8")
    return path


def call(when: datetime, model: str = "claude-opus-5-5", session: str = "s", **tokens: int) -> Call:
    counts = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    return Call(time=when, session=session, model=model, web_searches=0, **{**counts, **tokens})


def test_calls_are_read_from_every_transcript_and_broken_lines_are_skipped(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a",
        json.dumps({"time": "2026-11-20T10:00:00+00:00", "type": "text_delta", "text": "hi"}),
        record("2026-11-20T10:00:01+00:00", input_tokens=100, output_tokens=20),
        '{"time": "2026-11-20T10:00:02+00:00", "type": "usage_updated", "input_tok',  # cut short
        json.dumps({"type": "text_delta", "text": 'it said "usage_updated"'}),
    )
    write(tmp_path, "b", record("2026-11-21T09:00:00+00:00", cache_read_tokens=5000))

    calls = read_calls(tmp_path)

    assert [(c.session, c.input_tokens, c.cache_read_tokens) for c in calls] == [
        ("a", 100, 0),
        ("b", 0, 5000),
    ]
    assert read_calls(tmp_path / "nowhere") == []


def test_a_deleted_sessions_usage_is_kept(tmp_path: Path) -> None:
    path = write(tmp_path, "gone", record("2026-11-20T10:00:00+00:00", input_tokens=7))
    before = read_calls(tmp_path)

    archive(tmp_path, "gone")
    path.unlink()
    archive(tmp_path, "never-was")  # nothing to keep, and no error

    assert read_calls(tmp_path) == before
    assert read_calls(tmp_path)[0].session == "gone"


def test_buckets_start_on_the_day_monday_first_of_month_and_new_year() -> None:
    sunday = date(2026, 11, 22)

    assert bucket_start(sunday, "day") == sunday
    assert bucket_start(sunday, "week") == date(2026, 11, 16)
    assert bucket_start(sunday, "month") == date(2026, 11, 1)
    assert bucket_start(sunday, "year") == date(2026, 1, 1)


def test_totals_for_today_this_week_month_year_and_all_time() -> None:
    now = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)  # a Sunday
    calls = [
        call(now - timedelta(hours=1), input_tokens=10, output_tokens=1, session="a"),
        call(now - timedelta(days=3), input_tokens=20, session="a"),  # this week
        call(now - timedelta(days=10), input_tokens=40, session="b"),  # this month
        call(now - timedelta(days=60), input_tokens=80, session="c"),  # this year
        call(now - timedelta(days=400), input_tokens=160, session="d"),  # last year
    ]

    found = summarize(calls, now)
    totals = found["totals"]

    assert [totals[p]["input_tokens"] for p in ("day", "week", "month", "year", "all")] == [
        10,
        30,
        70,
        150,
        310,
    ]
    assert totals["day"]["tokens"] == 11
    assert (totals["week"]["sessions"], totals["all"]["sessions"]) == (1, 4)
    assert (totals["all"]["calls"], found["first"]) == (5, "2025-10-18")


def test_each_series_is_oldest_first_with_empty_buckets_and_years_go_back_to_the_first_call() -> (
    None
):
    now = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)
    calls = [call(now, output_tokens=5), call(now - timedelta(days=400), output_tokens=3)]

    series = summarize(calls, now)["series"]

    assert (len(series["day"]), len(series["week"]), len(series["month"])) == (30, 12, 12)
    assert (series["day"][0]["start"], series["day"][-1]["start"]) == ("2026-10-24", "2026-11-22")
    assert series["day"][-1]["output_tokens"] == 5 and series["day"][-2]["tokens"] == 0
    assert series["week"][-1]["start"] == "2026-11-16"
    assert [m["start"] for m in series["month"][-2:]] == ["2026-10-01", "2026-11-01"]
    assert [(y["start"], y["output_tokens"]) for y in series["year"]] == [
        ("2025-01-01", 3),
        ("2026-01-01", 5),
    ]


def test_a_day_is_the_readers_day_not_utcs() -> None:
    pacific = timezone(timedelta(hours=-8))
    now = datetime(2026, 11, 21, 23, 30, tzinfo=pacific)
    late = datetime(2026, 11, 22, 7, 0, tzinfo=UTC)  # 11pm on the 21st in California

    found = summarize([call(late, input_tokens=9)], now)

    assert found["totals"]["day"]["input_tokens"] == 9
    assert found["series"]["day"][-1]["start"] == "2026-11-21"


def test_models_are_listed_by_tokens_a_local_one_is_free_and_an_unpriced_one_has_no_dollars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As after the config is read: models on this machine cost nothing.
    monkeypatch.setattr(pricing, "EXTRA_PRICES", {})
    monkeypatch.setattr(pricing, "FREE_PROVIDERS", {"ollama"})
    now = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)
    calls = [
        call(now, "claude-opus-5-5", input_tokens=1_000_000),
        call(now, "ollama/qwen3-coder:30b", input_tokens=3_000_000, output_tokens=10),
        call(now, "together/some-model", input_tokens=2_000_000),
    ]

    found = summarize(calls, now)
    rows = [(m["model"], m["dollars"], m["unpriced_calls"]) for m in found["models"]]

    assert rows == [
        ("ollama/qwen3-coder:30b", 0.0, 0),
        ("together/some-model", 0.0, 1),
        ("claude-opus-5-5", 4.0, 0),
    ]
    assert found["totals"]["all"]["dollars"] == 4.0
    assert found["totals"]["all"]["unpriced_calls"] == 1


def test_with_nothing_used_everything_is_zero() -> None:
    now = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)

    found = summarize([], now)

    assert found["first"] is None and found["models"] == []
    assert found["totals"]["all"]["tokens"] == 0
    assert [y["start"] for y in found["series"]["year"]] == ["2026-01-01"]


def test_the_calendar_covers_a_year_of_weeks_with_the_days_that_had_use() -> None:
    now = datetime(2026, 11, 22, 15, 0, tzinfo=UTC)  # a Sunday
    calls = [
        call(now - timedelta(hours=1), input_tokens=10, session="a"),
        call(now - timedelta(hours=2), output_tokens=5, session="b"),
        call(now - timedelta(days=3), input_tokens=20, session="a"),
        call(now - timedelta(days=400), input_tokens=160, session="d"),  # before it starts
    ]

    calendar = summarize(calls, now)["calendar"]

    assert calendar["start"] == "2025-11-17" and calendar["end"] == "2026-11-22"  # 53 weeks
    assert [(d["day"], d["tokens"], d["calls"], d["sessions"]) for d in calendar["days"]] == [
        ("2026-11-19", 20, 1, 1),
        ("2026-11-22", 15, 2, 2),
    ]
