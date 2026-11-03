"""Eval reports for the dashboard: the runs in evals/reports/, one run, a transcript, and a
comparison of two runs."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from zwans.eval.compare import compare
from zwans.eval.runner import Report


class ReportNotFound(Exception):
    pass


def list_runs(reports: Path) -> list[dict[str, Any]]:
    """Every run with a readable report, oldest first, without its attempts."""
    runs: list[dict[str, Any]] = []
    if not reports.is_dir():
        return runs
    for folder in reports.iterdir():
        try:
            report = _load(folder)
        except ReportNotFound:
            continue
        runs.append(
            {
                "name": folder.name,
                "agent": report.agent,
                "executor": report.executor,
                "config": report.config.name,
                "model": report.model,
                "effort": report.effort,
                "started_at": report.started_at,
                "repeats": report.repeats,
                "tasks": sorted(report.tasks),
                "summary": report.summary.model_dump(),
            }
        )
    return sorted(runs, key=lambda run: run["started_at"])


def get_run(reports: Path, name: str) -> dict[str, Any]:
    report = _load(_folder(reports, name))
    data = report.model_dump(mode="json")
    for attempt in data["attempts"]:  # the dashboard asks for transcripts by file name
        attempt["transcript"] = Path(attempt["transcript"]).name if attempt["transcript"] else ""
    return data


def get_transcript(reports: Path, name: str, file: str) -> list[dict[str, Any]]:
    if "/" in file or "\\" in file or not file.endswith(".jsonl"):
        raise ReportNotFound(file)
    path = _folder(reports, name) / "transcripts" / file
    if not path.is_file():
        raise ReportNotFound(file)
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def compare_runs(reports: Path, a: str, b: str) -> dict[str, Any]:
    first, second = _load(_folder(reports, a)), _load(_folder(reports, b))
    result = compare(first, second)
    return {
        "a": a,
        "b": b,
        "tasks": result.tasks,
        "only_in_a": result.only_in_a,
        "only_in_b": result.only_in_b,
        "differences": [
            {
                "metric": d.metric,
                "a": d.a,
                "b": d.b,
                "delta": d.delta,
                "low": d.low,
                "high": d.high,
                "significant": d.significant,
            }
            for d in result.differences
        ],
        "task_pass_rates": {task: list(rates) for task, rates in result.task_pass_rates.items()},
    }


def _folder(reports: Path, name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ReportNotFound(name)
    return reports / name


def _load(folder: Path) -> Report:
    try:
        return Report.model_validate_json((folder / "report.json").read_bytes())
    except (OSError, ValidationError) as exc:
        raise ReportNotFound(folder.name) from exc
