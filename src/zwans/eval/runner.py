"""Runs eval tasks: each attempt gets a fresh copy of a task's repo, the agent works on it,
then the task's check decides whether it passed.

Attempts run on this machine in a temporary folder for now. The Docker executor (Phase 4)
will give each one its own container.
"""

import asyncio
import contextlib
import tempfile
import time
import tomllib
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from zwans.config import Config
from zwans.context.compaction import Compactor
from zwans.context.instructions import load_instructions
from zwans.eval.injection import CarefulUser, PlantedActions
from zwans.eval.task import Injection, Task, prepare_workspace, run_check
from zwans.events import Error, Event, ToolCallRequested, ToolResult, UsageUpdated
from zwans.executor.docker import SANDBOX_OS, DockerError, DockerExecutor
from zwans.executor.local import LocalExecutor, find_bash
from zwans.policy import Permissions, Policy
from zwans.pricing import cost
from zwans.prompt import system_prompt
from zwans.providers.base import Provider
from zwans.session import Session
from zwans.tools.base import Tool, ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.read import ReadTool
from zwans.tools.write import WriteTool
from zwans.transcript import TranscriptWriter

CHECK_OUTPUT_CHARS = 2_000  # the end of the check's output, kept in the report

type ProviderFactory = Callable[[Task, Config], Provider]
type Status = Literal["passed", "failed", "stopped"]


class EvalConfigError(Exception):
    pass


class EvalConfig(BaseModel):
    """One way of running the agent, to compare against another: evals/configs/<name>.toml.

    Top-level keys override Zwans's own settings (model, effort, max_steps, ...). A
    [tool_descriptions] table replaces what the model is told about a tool, by tool name.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    settings: dict[str, Any] = {}
    tool_descriptions: dict[str, str] = {}

    def apply(self, base: Config) -> Config:
        try:
            return Config.model_validate({**base.model_dump(), **self.settings})
        except ValidationError as exc:
            raise EvalConfigError(f"Config {self.name}: {exc}") from exc


def load_eval_config(path: Path) -> EvalConfig:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        descriptions = data.pop("tool_descriptions", {})
        return EvalConfig(name=path.stem, settings=data, tool_descriptions=descriptions)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise EvalConfigError(f"{path}: {exc}") from exc


def make_tools(config: EvalConfig) -> list[Tool[Any]]:
    tools: list[Tool[Any]] = [
        ReadTool(),
        WriteTool(),
        EditTool(),
        GlobTool(),
        GrepTool(),
        BashTool(),
    ]
    names = {tool.name for tool in tools}
    unknown = sorted(set(config.tool_descriptions) - names)
    if unknown:
        raise EvalConfigError(f"Config {config.name} describes unknown tools: {unknown}")
    for tool in tools:
        if tool.name in config.tool_descriptions:
            tool.description = config.tool_descriptions[tool.name]
    return tools


class AttemptResult(BaseModel):
    task: str
    category: str
    repeat: int  # 1, 2, ... for repeats of the same task
    # "stopped" means the suite's budget ran out first; such attempts count for nothing.
    status: Status
    stop_reason: str  # why the agent's turn ended: "end_turn", "timeout", "over_budget", ...
    dollars: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    seconds: float = 0.0
    check_exit: int | None = None
    check_output: str = ""
    errors: list[str] = []
    transcript: str = ""
    # Injection tasks only: tool calls carrying a planted instruction's canary.
    planted_attempts: list[str] = []  # the agent tried them
    planted_runs: list[str] = []  # they ran; any of these fails the attempt


class Summary(BaseModel):
    attempts: int  # attempts that count: every one that wasn't stopped
    passed: int
    pass_rate: float
    dollars: float  # in total, stopped attempts included
    mean_dollars: float
    mean_model_calls: float
    mean_tool_calls: float
    tool_error_rate: float  # failed tool calls out of all tool calls
    mean_seconds: float
    planted_attempts: int = 0
    planted_runs: int = 0

    @classmethod
    def of(cls, results: Sequence[AttemptResult]) -> "Summary":
        counted = [r for r in results if r.status != "stopped"]
        n = len(counted)
        tool_calls = sum(r.tool_calls for r in counted)

        def mean(values: list[float]) -> float:
            return sum(values) / n if n else 0.0

        passed = sum(r.status == "passed" for r in counted)
        return cls(
            attempts=n,
            passed=passed,
            pass_rate=passed / n if n else 0.0,
            dollars=sum(r.dollars for r in results),
            mean_dollars=mean([r.dollars for r in counted]),
            mean_model_calls=mean([r.model_calls for r in counted]),
            mean_tool_calls=mean([r.tool_calls for r in counted]),
            tool_error_rate=sum(r.tool_errors for r in counted) / tool_calls if tool_calls else 0.0,
            mean_seconds=mean([r.seconds for r in counted]),
            planted_attempts=sum(len(r.planted_attempts) for r in counted),
            planted_runs=sum(len(r.planted_runs) for r in counted),
        )


class Report(BaseModel):
    agent: str = "zwans"  # or "claude-code", for the baseline
    executor: str = "local"  # where the agent's commands ran: "local" or "docker"
    config: EvalConfig
    model: str
    effort: str
    started_at: str
    repeats: int
    budget: float | None  # dollars for the whole run
    out_of_budget: bool  # the run stopped early because the budget ran out
    summary: Summary
    tasks: dict[str, Summary]
    attempts: list[AttemptResult]


@dataclass
class Budget:
    """Dollars the whole run may spend. Every attempt charges it as it goes."""

    limit: float | None
    spent: float = 0.0

    @property
    def exhausted(self) -> bool:
        return self.limit is not None and self.spent >= self.limit


@dataclass
class AgentRun:
    """What an agent did in one attempt, whichever agent it was."""

    stop_reason: str  # "end_turn", "timeout", "over_budget", "suite_budget", ...
    dollars: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    errors: list[str] = field(default_factory=list)
    planted_attempts: list[str] = field(default_factory=list)
    planted_runs: list[str] = field(default_factory=list)


class Agent(Protocol):
    name: str

    async def attempt(
        self, task: Task, workspace: Path, scratch: Path, budget: Budget, transcript: Path
    ) -> AgentRun:
        """Work on the task in `workspace`, keeping within its timeout, its max_cost, and the
        run's budget, which it charges as it spends. `scratch` is a folder outside the
        workspace for the agent's own files. The event log goes to `transcript`."""
        ...


class ZwansAgent:
    name = "zwans"

    def __init__(
        self, config: Config, eval_config: EvalConfig, make_provider: ProviderFactory
    ) -> None:
        self.config = config
        self.eval_config = eval_config
        self.make_provider = make_provider

    async def attempt(
        self, task: Task, workspace: Path, scratch: Path, budget: Budget, transcript: Path
    ) -> AgentRun:
        try:
            async with self._executor(workspace, scratch) as executor:
                return await self._attempt(task, workspace, executor, budget, transcript)
        except DockerError as exc:
            return AgentRun(stop_reason="error", errors=[str(exc)])

    @contextlib.asynccontextmanager
    async def _executor(self, workspace: Path, scratch: Path) -> AsyncIterator[LocalExecutor]:
        spill = scratch / "output"
        if self.config.executor == "docker":
            async with DockerExecutor(workspace, spill_dir=spill) as executor:
                yield executor
        else:
            yield LocalExecutor(workspace, shell=self.config.shell, spill_dir=spill)

    async def _attempt(
        self,
        task: Task,
        workspace: Path,
        executor: LocalExecutor,
        budget: Budget,
        transcript: Path,
    ) -> AgentRun:
        watch = _Watch(task, budget)
        writer = TranscriptWriter(transcript)
        planted = PlantedActions(task.injection.canaries if task.injection else [])
        provider = self.make_provider(task, self.config)
        listeners: list[Callable[[Event], None]] = [
            watch.on_event,
            writer.on_event,
            planted.on_event,
        ]
        session = self._session(workspace, provider, executor, listeners)
        if task.injection is not None:
            session.permissions = _injection_permissions(task.injection, executor)
        try:
            watch.turn = asyncio.create_task(session.send(task.prompt))
            stop_reason = await asyncio.wait_for(watch.turn, task.timeout)
        except TimeoutError:
            stop_reason = "timeout"
        except asyncio.CancelledError:
            if not watch.stopped_by:
                raise  # cancelled from outside, not by a budget
            stop_reason = watch.stopped_by
        finally:
            await provider.aclose()
            writer.close()
        return AgentRun(
            stop_reason=stop_reason,
            dollars=watch.dollars,
            model_calls=watch.model_calls,
            tool_calls=watch.tool_calls,
            tool_errors=watch.tool_errors,
            errors=watch.errors,
            planted_attempts=planted.attempted,
            planted_runs=planted.ran,
        )

    def _session(
        self,
        workspace: Path,
        provider: Provider,
        executor: LocalExecutor,
        listeners: list[Callable[[Event], None]],
    ) -> Session:
        # Only the task's own ZWANS.md, never the user's, so every attempt gets the same prompt.
        instructions = load_instructions(workspace, home=workspace)
        if isinstance(executor, DockerExecutor):
            system = system_prompt(workspace, "bash", instructions, SANDBOX_OS)
        else:
            system = system_prompt(workspace, self.config.shell or _find_bash(), instructions)
        return Session(
            provider=provider,
            tools=make_tools(self.eval_config),
            ctx=ToolContext(executor=executor),
            system=system,
            listeners=listeners,
            max_steps=self.config.max_steps,
            compactor=Compactor(provider, self.config.compact_at, self.config.keep_messages),
        )


@dataclass
class _Watch:
    """Listens to one attempt's events: counts what the report needs and enforces the
    attempt's and the run's budgets by cancelling the turn."""

    task: Task
    budget: Budget
    turn: asyncio.Task[str] | None = None
    dollars: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_by: str = ""  # "over_budget" (this attempt's) or "suite_budget" (the run's)

    def on_event(self, event: Event) -> None:
        if isinstance(event, UsageUpdated):
            self.model_calls += 1
            dollars = cost(event) or 0.0
            self.dollars += dollars
            self.budget.spent += dollars
            if self.dollars > self.task.max_cost:
                self._stop("over_budget")
            elif self.budget.exhausted:
                self._stop("suite_budget")
        elif isinstance(event, ToolCallRequested):
            self.tool_calls += 1
        elif isinstance(event, ToolResult) and event.is_error:
            self.tool_errors += 1
        elif isinstance(event, Error):
            self.errors.append(event.message)

    def _stop(self, reason: str) -> None:
        if not self.stopped_by and self.turn is not None:
            self.stopped_by = reason
            self.turn.cancel()


def _injection_permissions(injection: Injection, executor: LocalExecutor) -> Permissions:
    policy = Policy.default()
    policy.mode = injection.mode
    approver = CarefulUser(injection, executor.contains, executor.relative)
    return Permissions(policy, executor.contains, executor.relative, approver)


def _find_bash() -> str:
    try:
        return find_bash()
    except FileNotFoundError:
        return "none found, so the Bash tool will fail"


async def run_attempt(
    task: Task, repeat: int, agent: Agent, budget: Budget, transcript: Path, shell: str | None
) -> AttemptResult:
    result = AttemptResult(
        task=task.name,
        category=task.category,
        repeat=repeat,
        status="stopped",
        stop_reason="suite_budget",
    )
    if budget.exhausted:
        return result
    with tempfile.TemporaryDirectory(prefix=f"zwans-eval-{task.name}-") as temp:
        workspace = Path(temp) / "work"
        prepare_workspace(task, workspace)
        started = time.monotonic()
        run = await agent.attempt(task, workspace, Path(temp), budget, transcript)
        result.seconds = round(time.monotonic() - started, 2)
        result.stop_reason = run.stop_reason
        result.dollars = run.dollars
        result.model_calls = run.model_calls
        result.tool_calls = run.tool_calls
        result.tool_errors = run.tool_errors
        result.errors = run.errors
        result.transcript = str(transcript)
        result.planted_attempts = run.planted_attempts
        result.planted_runs = run.planted_runs
        if run.stop_reason == "suite_budget":
            return result  # stays "stopped"
        result.status = "failed"
        if run.planted_runs:
            return result  # a planted action ran, so the attempt fails whatever the check says
        if run.stop_reason not in ("timeout", "over_budget"):  # running out of limits is a fail
            executor = LocalExecutor(workspace, shell=shell, spill_dir=Path(temp) / "output")
            check = await run_check(task, executor)
            result.check_exit = check.exit_code
            result.check_output = check.output[-CHECK_OUTPUT_CHARS:]
            result.status = "passed" if check.exit_code == 0 else "failed"
        return result


async def run_suite(
    tasks: Sequence[Task],
    agent: Agent,
    config: Config,
    eval_config: EvalConfig,
    out_dir: Path,
    *,
    repeats: int = 1,
    parallel: int = 4,
    budget: float | None = None,
    on_result: Callable[[AttemptResult], None] | None = None,
) -> Report:
    """Run every task `repeats` times, up to `parallel` attempts at once, and save
    out_dir/report.json. Attempts are ordered so each task's first try comes before
    any task's second, which keeps an early budget stop from skipping whole tasks."""
    started_at = datetime.now().isoformat(timespec="seconds")
    spend = Budget(budget)
    slots = asyncio.Semaphore(parallel)

    async def attempt(task: Task, repeat: int) -> AttemptResult:
        async with slots:
            path = out_dir / "transcripts" / f"{task.name}-{repeat}.jsonl"
            result = await run_attempt(task, repeat, agent, spend, path, config.shell)
        if on_result is not None:
            on_result(result)
        return result

    jobs = [attempt(task, repeat) for repeat in range(1, repeats + 1) for task in tasks]
    results = sorted(await asyncio.gather(*jobs), key=lambda r: (r.task, r.repeat))

    report = Report(
        agent=agent.name,
        executor=config.executor if agent.name == "zwans" else "local",
        config=eval_config,
        model=config.model,
        effort=config.effort,
        started_at=started_at,
        repeats=repeats,
        budget=budget,
        out_of_budget=any(r.status == "stopped" for r in results),
        summary=Summary.of(results),
        tasks={t.name: Summary.of([r for r in results if r.task == t.name]) for t in tasks},
        attempts=results,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report
