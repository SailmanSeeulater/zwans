"""`zwans eval`: run the eval suite and report how the agent did."""

import asyncio
import shutil
import subprocess
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from zwans.config import Config, ConfigError, load_credential, load_settings
from zwans.eval.claude_code import ClaudeCodeAgent
from zwans.eval.codex import CodexAgent
from zwans.eval.compare import MIN_TASKS, Difference, compare
from zwans.eval.html import render_html
from zwans.eval.runner import (
    Agent,
    AttemptResult,
    EvalConfig,
    EvalConfigError,
    ProviderFactory,
    Report,
    ZwansAgent,
    check_the_checks,
    load_eval_config,
    run_suite,
)
from zwans.eval.task import Task, TaskError, load_suite, split_suite
from zwans.executor.docker import DockerError, ensure_sandbox_network
from zwans.executor.jail import find_jail
from zwans.executor.seatbelt import find_sandbox
from zwans.pricing import price_of
from zwans.providers.base import Provider
from zwans.providers.catalog import register_prices, resolve
from zwans.providers.fake import FakeProvider
from zwans.providers.router import ModelRouter

eval_app = typer.Typer(no_args_is_help=True, help="Run eval tasks and report the results.")

STATUS_MARKS = {"passed": "PASS", "failed": "FAIL", "stopped": "STOP", "errored": "ERR "}


class ExecutorName(StrEnum):
    local = "local"
    docker = "docker"
    jail = "jail"
    seatbelt = "seatbelt"


class SplitPart(StrEnum):
    train = "train"
    test = "test"


class AgentName(StrEnum):
    zwans = "zwans"
    claude_code = "claude-code"
    codex = "codex"


@eval_app.command("run")
def run_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="An evals/configs file."),
    ] = None,
    agent_name: Annotated[
        AgentName,
        typer.Option(
            "--agent",
            help="Who does the tasks: claude-code or codex (with an openai/<model>) "
            "for a baseline.",
        ),
    ] = AgentName.zwans,
    tasks_dir: Annotated[
        Path, typer.Option("--tasks", exists=True, file_okay=False, help="Folder of tasks.")
    ] = Path("evals/tasks"),
    only: Annotated[
        list[str] | None, typer.Option(help="Run just this task. Repeat for several.")
    ] = None,
    executor: Annotated[
        ExecutorName | None,
        typer.Option(help="Where Zwans runs commands. Default: the `executor` setting."),
    ] = None,
    split: Annotated[
        SplitPart | None,
        typer.Option(help="Run one half of the suite: train to tune on, test to check it on."),
    ] = None,
    seed: Annotated[int, typer.Option(help="Which halves --split makes.")] = 0,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would run, without running it.")
    ] = False,
    repeats: Annotated[int, typer.Option(min=1, help="Attempts per task.")] = 1,
    parallel: Annotated[int, typer.Option(min=1, help="Attempts running at once.")] = 4,
    budget: Annotated[
        float | None, typer.Option(min=0, help="Stop the run once it has spent this many dollars.")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Folder for the report. Default: evals/reports/<time>-<config>."),
    ] = None,
    fake_scripts: Annotated[
        Path | None,
        typer.Option(hidden=True, help="Replay <task>.json from this folder instead of a model."),
    ] = None,
) -> None:
    """Run every task, check each attempt, and save a JSON and an HTML report."""
    try:
        base, env = load_settings()
        eval_config = load_eval_config(config_path) if config_path else EvalConfig(name="default")
        config = eval_config.apply(base)
        if executor is not None:
            config = config.model_copy(update={"executor": executor.value})
        if split is not None and only:
            raise TaskError("Use --split or --only, not both.")
        tasks = _select(load_suite(tasks_dir), only)
        if split is not None:
            tasks = split_suite(tasks, split.value, seed)
        if dry_run:
            _print_plan(tasks, repeats, agent_name, config, eval_config, budget)
            return
        agent = _agent(agent_name, config, eval_config, env, fake_scripts)
        if config.executor == "docker" and agent_name is AgentName.zwans:
            asyncio.run(ensure_sandbox_network())  # fail now rather than in every attempt
        if config.executor == "jail" and agent_name is AgentName.zwans:
            find_jail()  # the same: say now if it isn't built
        if config.executor == "seatbelt" and agent_name is AgentName.zwans:
            find_sandbox()  # and here, if this isn't a Mac
        problem = asyncio.run(check_the_checks(tasks, config.shell))
        if problem:
            raise TaskError(problem)
    except (ConfigError, EvalConfigError, TaskError, DockerError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc

    out = out or Path("evals/reports") / f"{datetime.now():%Y%m%d-%H%M%S}-{eval_config.name}"
    attempts = len(tasks) * repeats
    limit = f", budget ${budget:.2f}" if budget is not None else ""
    part = f" | {split.value} half, seed {seed}" if split is not None else ""
    typer.secho(
        f"{_count(len(tasks), 'task')} x {repeats} = {attempts} attempts | "
        f"{agent.name} ({config.executor}) | config {eval_config.name} | {config.model}, "
        f"effort {config.effort}{limit}{part}",
        dim=True,
    )
    report = asyncio.run(
        run_suite(
            tasks,
            agent,
            config,
            eval_config,
            out,
            repeats=repeats,
            parallel=parallel,
            budget=budget,
            split=f"{split.value}, seed {seed}" if split is not None else "",
            on_result=_print_attempt,
        )
    )
    _print_report(report)
    (out / "report.html").write_text(render_html(report, out), encoding="utf-8")
    typer.secho(f"Report: {out / 'report.html'} (and report.json)", dim=True)
    broken = [a for a in report.attempts if a.status == "errored"]
    if broken:
        # Usually the API refusing the request, which says nothing about the agent's skill.
        first = next((a.errors[0] for a in broken if a.errors), "no message")
        typer.secho(
            f"{_count(len(broken), 'attempt')} ended with an error and "
            f"{'was' if len(broken) == 1 else 'were'} neither checked nor counted. "
            f"First error: {first}",
            fg="yellow",
        )
    peeked = [a for a in report.attempts if a.peeks]
    if peeked:
        typer.secho(
            f"{_count(len(peeked), 'attempt')} reached for the task's answer and failed. "
            f"First call: {peeked[0].peeks[0]}",
            fg="yellow",
        )
    if report.out_of_budget:
        typer.secho("The budget ran out before every attempt finished.", fg="yellow")
        raise typer.Exit(1)


ReportPath = Annotated[
    Path, typer.Argument(exists=True, help="A run's report folder, or its report.json.")
]


@eval_app.command("compare")
def compare_command(a: ReportPath, b: ReportPath) -> None:
    """Show how run B differs from run A, with 95% confidence intervals.

    A difference is marked significant only when its interval leaves out zero.
    """
    try:
        report_a, report_b = _load_report(a), _load_report(b)
    except (OSError, ValueError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc
    result = compare(report_a, report_b)
    typer.secho(
        f"A: {report_a.agent}, config {report_a.config.name} ({report_a.started_at})\n"
        f"B: {report_b.agent}, config {report_b.config.name} ({report_b.started_at})\n"
        f"{_count(len(result.tasks), 'task')} in both",
        dim=True,
    )
    if len(result.tasks) < MIN_TASKS:
        typer.secho(
            f"Fewer than {MIN_TASKS} tasks in common, too few to call any difference real.",
            fg="yellow",
        )
    for name, missing in (("A", result.only_in_a), ("B", result.only_in_b)):
        if missing:
            typer.secho(f"Only in {name}, left out: {', '.join(missing)}", fg="yellow")

    typer.echo(f"\n{'':<12} {'A':>8} {'B':>8} {'B - A':>9}   95% interval")
    for diff in result.differences:
        typer.echo(_difference_line(diff))

    changed = {t: ab for t, ab in result.task_pass_rates.items() if ab[0] != ab[1]}
    if changed:
        typer.echo("\nTasks whose pass rate changed:")
        width = max(len(t) for t in changed)
        for task, (rate_a, rate_b) in sorted(changed.items(), key=lambda i: i[1][1] - i[1][0]):
            typer.echo(f"  {task:<{width}}  {rate_a:4.0%} -> {rate_b:4.0%}")


def _load_report(path: Path) -> Report:
    file = path / "report.json" if path.is_dir() else path
    return Report.model_validate_json(file.read_text(encoding="utf-8"))


def _difference_line(diff: Difference) -> str:
    if diff.metric == "pass rate":
        values = (f"{diff.a:.0%}", f"{diff.b:.0%}", f"{diff.delta * 100:+.0f} pts")
        interval = f"[{diff.low * 100:+.0f}, {diff.high * 100:+.0f}] pts"
    else:
        digits = 4 if diff.metric == "dollars" else 1
        values = (f"{diff.a:.{digits}f}", f"{diff.b:.{digits}f}", f"{diff.delta:+.{digits}f}")
        interval = f"[{diff.low:+.{digits}f}, {diff.high:+.{digits}f}]"
    line = f"{diff.metric:<12} {values[0]:>8} {values[1]:>8} {values[2]:>9}   {interval}"
    if diff.significant:
        line += "  " + typer.style("significant", bold=True)
    return line


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _print_plan(
    tasks: list[Task],
    repeats: int,
    agent: AgentName,
    config: Config,
    eval_config: EvalConfig,
    budget: float | None,
) -> None:
    """What a run would do, for --dry-run: nothing is run, checked or charged."""
    most = sum(task.max_cost for task in tasks) * repeats
    if budget is not None:
        most = min(most, budget)
    typer.echo(
        f"{_count(len(tasks), 'task')} x {repeats} = {len(tasks) * repeats} attempts | "
        f"{agent.value} ({config.executor}) | config {eval_config.name} | {config.model}, "
        f"effort {config.effort}"
    )
    width = max([len(task.name) for task in tasks] + [4])
    for task in tasks:
        typer.echo(f"  {task.name:<{width}}  {task.category:<10}  up to ${task.max_cost:.2f}")
    typer.echo(f"At most ${most:.2f} in all, from the tasks' max_cost and the budget.")


def _select(tasks: list[Task], only: list[str] | None) -> list[Task]:
    if not only:
        return tasks
    by_name = {task.name: task for task in tasks}
    missing = [name for name in only if name not in by_name]
    if missing:
        raise TaskError(f"No such task: {', '.join(missing)}")
    return [by_name[name] for name in only]


def _agent(
    name: AgentName,
    config: Config,
    eval_config: EvalConfig,
    env: dict[str, str],
    fake_scripts: Path | None,
) -> Agent:
    if name is AgentName.zwans:
        return ZwansAgent(config, eval_config, _provider_factory(config, env, fake_scripts))
    other = "Claude Code" if name is AgentName.claude_code else "Codex"
    if eval_config.tool_descriptions:
        raise EvalConfigError(f"Tool descriptions only apply to Zwans, not to {other}.")
    if eval_config.hooks:
        raise EvalConfigError(f"Hooks only apply to Zwans, not to {other}.")
    if name is AgentName.codex:
        return _codex_agent(config, env)
    claude = shutil.which("claude")
    if claude is None:
        raise ConfigError("Claude Code isn't installed: there's no `claude` on PATH.")
    # --bare takes only an API key, so ask for one whatever `auth` is set to.
    credential = load_credential(config.model_copy(update={"auth": "api_key"}), env)
    version = subprocess.run(
        [claude, "--version"], capture_output=True, text=True, timeout=60, check=False
    ).stdout.split()
    return ClaudeCodeAgent(config, credential.token, [claude], version[0] if version else "")


def _codex_agent(config: Config, env: dict[str, str]) -> CodexAgent:
    codex = shutil.which("codex")
    if codex is None:
        raise ConfigError("Codex isn't installed: there's no `codex` on PATH.")
    resolved = resolve(config.model, config, env)  # also says when OPENAI_API_KEY is missing
    if resolved.provider != "openai" or resolved.info is None:
        raise ConfigError(f"Codex runs OpenAI models, not {config.model}: use openai/<model>.")
    register_prices(config)
    version = subprocess.run(
        [codex, "--version"], capture_output=True, text=True, timeout=60, check=False
    ).stdout.split()
    try:
        return CodexAgent(
            config,
            resolved.info.key(env) or "",
            price_of(resolved.name),
            [codex],
            version[-1] if version else "",  # "codex-cli 0.171.0"
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _provider_factory(
    config: Config, env: dict[str, str], fake_scripts: Path | None
) -> ProviderFactory:
    if fake_scripts is not None:
        scripts = fake_scripts

        def fake(task: Task, config: Config) -> Provider:
            return FakeProvider.from_file(scripts / f"{task.name}.json")

        return fake

    resolve(config.model, config, env)  # checks the model and its key once, before any attempt

    def real(task: Task, config: Config) -> Provider:
        return ModelRouter(config, env, config.model)

    return real


def _print_attempt(result: AttemptResult) -> None:
    colour = {"passed": "green", "failed": "red"}.get(result.status, "yellow")
    mark = typer.style(STATUS_MARKS[result.status], fg=colour)
    detail = f"{result.model_calls} model calls, ${result.dollars:.4f}, {result.seconds:.1f}s"
    if result.stop_reason != "end_turn":
        detail += f", stopped: {result.stop_reason}"
    if result.peeks:
        detail += ", reached for the answer"
    if result.planted_attempts:
        ran = len(result.planted_runs)
        detail += f", tried {len(result.planted_attempts)} planted actions, {ran} ran"
    typer.echo(f"{mark} {result.task} #{result.repeat}  {detail}")


def _print_report(report: Report) -> None:
    width = max([len(name) for name in report.tasks] + [4])
    typer.echo(f"\n{'task':<{width}}  passed  mean $  calls  tools  errors")
    for name, s in [*report.tasks.items(), ("all", report.summary)]:
        typer.echo(
            f"{name:<{width}}  {s.passed:>2}/{s.attempts:<3}  {s.mean_dollars:6.3f}  "
            f"{s.mean_model_calls:5.1f}  {s.mean_tool_calls:5.1f}  {s.tool_error_rate:6.0%}"
        )
    s = report.summary
    errored = f", {s.errored} errored and not counted" if s.errored else ""
    typer.echo(
        f"\nPass rate {s.pass_rate:.0%} ({s.passed}/{s.attempts}){errored}, spent ${s.dollars:.4f}"
    )
    typer.echo(f"Cache hits {s.cache_hit_rate:.0%} of input tokens", nl=False)
    typer.echo(f", {s.mean_compactions:.1f} compactions per attempt" if s.mean_compactions else "")
    if any(r.planted_attempts for r in report.attempts):
        typer.echo(
            f"Planted actions: the agent tried {s.planted_attempts}, and {s.planted_runs} ran."
        )
