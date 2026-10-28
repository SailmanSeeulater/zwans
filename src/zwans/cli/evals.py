"""`zwans eval`: run the eval suite and report how the agent did."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from zwans.config import Config, ConfigError, load_credential, load_settings
from zwans.eval.runner import (
    AttemptResult,
    EvalConfig,
    EvalConfigError,
    ProviderFactory,
    Report,
    load_eval_config,
    run_suite,
)
from zwans.eval.task import Task, TaskError, load_suite
from zwans.providers.anthropic import AnthropicProvider
from zwans.providers.base import Provider
from zwans.providers.fake import FakeProvider

eval_app = typer.Typer(no_args_is_help=True, help="Run eval tasks and report the results.")

STATUS_MARKS = {"passed": "PASS", "failed": "FAIL", "stopped": "STOP"}


@eval_app.command("run")
def run_command(
    config_path: Annotated[
        Path | None,
        typer.Option("--config", "-c", exists=True, dir_okay=False, help="An evals/configs file."),
    ] = None,
    tasks_dir: Annotated[
        Path, typer.Option("--tasks", exists=True, file_okay=False, help="Folder of tasks.")
    ] = Path("evals/tasks"),
    only: Annotated[
        list[str] | None, typer.Option(help="Run just this task. Repeat for several.")
    ] = None,
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
    """Run every task, check each attempt, and save a JSON report."""
    try:
        base, env = load_settings()
        eval_config = load_eval_config(config_path) if config_path else EvalConfig(name="default")
        config = eval_config.apply(base)
        tasks = _select(load_suite(tasks_dir), only)
        make_provider = _provider_factory(config, env, fake_scripts)
    except (ConfigError, EvalConfigError, TaskError) as exc:
        typer.secho(str(exc), fg="red", err=True)
        raise typer.Exit(2) from exc

    out = out or Path("evals/reports") / f"{datetime.now():%Y%m%d-%H%M%S}-{eval_config.name}"
    attempts = len(tasks) * repeats
    limit = f", budget ${budget:.2f}" if budget is not None else ""
    noun = "task" if len(tasks) == 1 else "tasks"
    typer.secho(
        f"{len(tasks)} {noun} x {repeats} = {attempts} attempts | config {eval_config.name} | "
        f"{config.model}, effort {config.effort}{limit}",
        dim=True,
    )
    report = asyncio.run(
        run_suite(
            tasks,
            config,
            eval_config,
            make_provider,
            out,
            repeats=repeats,
            parallel=parallel,
            budget=budget,
            on_result=_print_attempt,
        )
    )
    _print_report(report)
    typer.secho(f"Report: {out / 'report.json'}", dim=True)
    if report.out_of_budget:
        typer.secho("The budget ran out before every attempt finished.", fg="yellow")
        raise typer.Exit(1)


def _select(tasks: list[Task], only: list[str] | None) -> list[Task]:
    if not only:
        return tasks
    by_name = {task.name: task for task in tasks}
    missing = [name for name in only if name not in by_name]
    if missing:
        raise TaskError(f"No such task: {', '.join(missing)}")
    return [by_name[name] for name in only]


def _provider_factory(
    config: Config, env: dict[str, str], fake_scripts: Path | None
) -> ProviderFactory:
    if fake_scripts is not None:
        scripts = fake_scripts

        def fake(task: Task, config: Config) -> Provider:
            return FakeProvider.from_file(scripts / f"{task.name}.json")

        return fake

    credential = load_credential(config, env)  # checked once, before any attempt starts

    def anthropic(task: Task, config: Config) -> Provider:
        return AnthropicProvider(credential, config.model, config.effort, config.max_tokens)

    return anthropic


def _print_attempt(result: AttemptResult) -> None:
    colour = {"passed": "green", "failed": "red"}.get(result.status, "yellow")
    mark = typer.style(STATUS_MARKS[result.status], fg=colour)
    detail = f"{result.model_calls} model calls, ${result.dollars:.4f}, {result.seconds:.1f}s"
    if result.stop_reason != "end_turn":
        detail += f", stopped: {result.stop_reason}"
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
    typer.echo(f"\nPass rate {s.pass_rate:.0%} ({s.passed}/{s.attempts}), spent ${s.dollars:.4f}")
