import random
from pathlib import Path

from typer.testing import CliRunner

from zwans.cli.app import app
from zwans.eval.compare import compare
from zwans.eval.html import render_html
from zwans.eval.runner import AttemptResult, EvalConfig, Report, Status, Summary


def attempt(task: str, repeat: int, status: Status, dollars: float = 0.1) -> AttemptResult:
    return AttemptResult(
        task=task,
        category="bug-fix",
        repeat=repeat,
        status=status,
        stop_reason="end_turn",
        dollars=dollars,
        model_calls=4,
        tool_calls=3,
    )


def report(name: str, attempts: list[AttemptResult]) -> Report:
    tasks = sorted({a.task for a in attempts})
    return Report(
        config=EvalConfig(name=name),
        model="claude-opus-5-5",
        effort="medium",
        started_at="2026-10-28T10:00:00",
        repeats=3,
        budget=None,
        out_of_budget=False,
        summary=Summary.of(attempts),
        tasks={t: Summary.of([a for a in attempts if a.task == t]) for t in tasks},
        attempts=attempts,
    )


def simulated(name: str, pass_chance: float, seed: int, tasks: int = 25) -> Report:
    """A run where each attempt passes with a task-specific chance around `pass_chance`."""
    rng = random.Random(seed)
    task_rng = random.Random(1)  # the same task difficulties in every run
    attempts = []
    for t in range(tasks):
        chance = min(1.0, max(0.0, pass_chance + task_rng.uniform(-0.3, 0.3)))
        for r in range(1, 4):
            status: Status = "passed" if rng.random() < chance else "failed"
            attempts.append(attempt(f"task-{t:02}", r, status))
    return report(name, attempts)


def test_the_same_run_shows_no_difference() -> None:
    run = simulated("a", 0.7, seed=1)

    for diff in compare(run, run).differences:
        assert diff.delta == 0
        assert not diff.significant


def test_noise_between_two_runs_of_the_same_config_is_not_significant() -> None:
    a = simulated("a", 0.7, seed=1)
    b = simulated("b", 0.7, seed=2)

    diff = next(d for d in compare(a, b).differences if d.metric == "pass rate")

    assert diff.delta != 0  # the runs do differ a little, by chance
    assert not diff.significant
    assert diff.low < 0 < diff.high


def test_a_real_drop_is_significant() -> None:
    a = simulated("a", 0.8, seed=1)
    b = simulated("b", 0.4, seed=2)

    diff = next(d for d in compare(a, b).differences if d.metric == "pass rate")

    assert diff.delta < -0.2
    assert diff.significant
    assert diff.high < 0


def test_only_shared_tasks_and_counted_attempts_are_compared() -> None:
    a = report("a", [attempt("x", 1, "passed"), attempt("y", 1, "passed")])
    stopped = attempt("x", 2, "stopped")
    b = report("b", [attempt("x", 1, "failed"), stopped, attempt("z", 1, "passed")])

    result = compare(a, b)

    assert result.tasks == ["x"]
    assert (result.only_in_a, result.only_in_b) == (["y"], ["z"])
    assert result.task_pass_rates == {"x": (1.0, 0.0)}


def test_compare_command(tmp_path: Path) -> None:
    for name, chance, seed in (("baseline", 0.8, 1), ("vague-edit", 0.4, 2)):
        (tmp_path / name).mkdir()
        run = simulated(name, chance, seed)
        (tmp_path / name / "report.json").write_text(run.model_dump_json(), "utf-8")

    result = CliRunner().invoke(
        app, ["eval", "compare", str(tmp_path / "baseline"), str(tmp_path / "vague-edit")]
    )

    assert result.exit_code == 0, result.output
    assert "25 tasks in both" in result.output
    pass_line = next(line for line in result.output.splitlines() if line.startswith("pass rate"))
    assert "significant" in pass_line
    assert "Tasks whose pass rate changed" in result.output


def test_html_report_lists_attempts_and_escapes_output(tmp_path: Path) -> None:
    failed = attempt("buggy-calc", 1, "failed")
    failed.check_exit = 1
    failed.check_output = "assert <3> == 4"
    failed.transcript = str(tmp_path / "transcripts" / "buggy-calc-1.jsonl")

    html = render_html(report("baseline", [failed, attempt("other", 1, "passed")]), tmp_path)

    assert "<title>Eval: baseline</title>" in html
    assert "assert &lt;3&gt; == 4" in html
    assert "href='transcripts/buggy-calc-1.jsonl'" in html
    assert "50%" in html


def test_too_few_tasks_are_never_significant() -> None:
    a = report("a", [attempt("x", r, "passed") for r in (1, 2, 3)])
    b = report("b", [attempt("x", r, "failed") for r in (1, 2, 3)])

    diff = compare(a, b).differences[0]

    assert diff.delta == -1.0
    assert not diff.significant
