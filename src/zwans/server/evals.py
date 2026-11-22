"""Eval reports for the dashboard: the runs in evals/reports/, one run, a transcript, a
comparison of two runs, and a leaderboard of everything run on the same tasks."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from zwans.eval.compare import MIN_TASKS, compare, pass_rate_difference, wilson
from zwans.eval.runner import AttemptResult, Report


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


def leaderboard(reports: Path) -> list[dict[str, Any]]:
    """Every task set that has runs, with those runs pooled by what ran (agent, model,
    effort, executor and config) and ranked: pass rate first, then cost per attempt.

    Only runs of exactly the same tasks share a board, since a pass rate on easy tasks says
    nothing against one on hard tasks. The boards with the most runs come first."""
    boards: dict[tuple[str, ...], dict[tuple[str, ...], list[tuple[str, Report]]]] = {}
    if reports.is_dir():
        for folder in reports.iterdir():
            try:
                report = _load(folder)
            except ReportNotFound:
                continue
            tasks = tuple(sorted(report.tasks))
            what = (report.agent, report.model, report.effort, report.executor, report.config.name)
            boards.setdefault(tasks, {}).setdefault(what, []).append((folder.name, report))
    found = [
        {"tasks": list(tasks), "runs": sum(map(len, groups.values())), "rows": _rank(groups)}
        for tasks, groups in boards.items()
        if tasks
    ]
    return sorted(found, key=lambda board: (-board["runs"], board["tasks"]))


def _rank(groups: dict[tuple[str, ...], list[tuple[str, Report]]]) -> list[dict[str, Any]]:
    pooled: list[tuple[dict[str, Any], list[AttemptResult]]] = []
    for (agent, model, effort, executor, config), runs in groups.items():
        runs = sorted(runs, key=lambda run: run[1].started_at)
        attempts = [a for _, report in runs for a in report.attempts if a.status != "stopped"]
        if not attempts:
            continue
        count = len(attempts)
        passed = sum(a.status == "passed" for a in attempts)
        low, high = wilson(passed, count)
        row = {
            "agent": agent,
            "model": model,
            "effort": effort,
            "executor": executor,
            "config": config,
            "runs": [name for name, _ in runs],  # oldest first
            "attempts": count,
            "passed": passed,
            "pass_rate": passed / count,
            "low": low,
            "high": high,
            "mean_dollars": sum(a.dollars for a in attempts) / count,
            "mean_seconds": sum(a.seconds for a in attempts) / count,
            "mean_model_calls": sum(a.model_calls for a in attempts) / count,
        }
        pooled.append((row, attempts))
    pooled.sort(key=lambda item: (-item[0]["pass_rate"], item[0]["mean_dollars"]))
    rows = [row for row, _ in pooled]
    for row, attempts in pooled:
        row["standing"] = "best" if row is rows[0] else _standing(pooled[0][1], attempts)
        # On the frontier: no other row passes at least as often for no more money.
        row["frontier"] = not any(_beats(other, row) for other in rows)
    return rows


def _standing(best: list[AttemptResult], attempts: list[AttemptResult]) -> str:
    """Whether a row is clearly behind the best one, or the tasks can't tell them apart."""
    difference = pass_rate_difference(best, attempts)
    if difference.tasks < MIN_TASKS:
        return "too_few_tasks"
    return "behind" if difference.significant and difference.delta < 0 else "level"


def _beats(a: dict[str, Any], b: dict[str, Any]) -> bool:
    at_least = a["pass_rate"] >= b["pass_rate"] and a["mean_dollars"] <= b["mean_dollars"]
    better = a["pass_rate"] > b["pass_rate"] or a["mean_dollars"] < b["mean_dollars"]
    return bool(at_least and better)


def _folder(reports: Path, name: str) -> Path:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ReportNotFound(name)
    return reports / name


def _load(folder: Path) -> Report:
    try:
        return Report.model_validate_json((folder / "report.json").read_bytes())
    except (OSError, ValidationError) as exc:
        raise ReportNotFound(folder.name) from exc
