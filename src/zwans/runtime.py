"""Opens a session with everything it needs, for the CLI and the server alike: the model,
the executor, the policy, the tools, the transcript, and the saved copy in sessions.db.

A chat is a session with no project: it gets an empty folder of its own under the home's
chats/ folder and none of Zwans's tools, so the model can only talk (and search the web,
where the model's provider offers that). Everything else is the same, so chats are saved,
listed, resumed and metered like any session, and where a session works says which it is."""

import contextlib
import secrets
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from zwans.budget import Budget
from zwans.checkpoints import Checkpoints
from zwans.config import Config, ConfigError
from zwans.context.compaction import Compactor
from zwans.context.instructions import load_instructions
from zwans.events import Event, ModelCalled, Rewound
from zwans.executor.background import BackgroundJobs
from zwans.executor.docker import SANDBOX_OS, DockerExecutor
from zwans.executor.jail import JAIL_OS, JailExecutor
from zwans.executor.local import LocalExecutor, find_bash
from zwans.executor.seatbelt import SEATBELT_OS, SeatbeltError, SeatbeltExecutor
from zwans.ext.hooks import Hooks
from zwans.ext.skills import find_skills, skill_folders
from zwans.followthrough import follow_through_for
from zwans.mcp.tools import McpServers, McpTool
from zwans.messages import Message
from zwans.policy.engine import Approver, Permissions
from zwans.policy.rules import LoadedPolicy, Mode, load_policy
from zwans.pricing import CostMeter
from zwans.prompt import chat_prompt, system_prompt
from zwans.providers.base import Provider
from zwans.providers.catalog import canonical, is_known
from zwans.providers.fake import FakeProvider
from zwans.providers.router import ModelRouter, helper
from zwans.session import Session
from zwans.store import SessionError, SessionInfo, SessionRecorder, SessionStore, load_session
from zwans.tools.archives import ArchiveTool
from zwans.tools.ask_user import AskUserTool
from zwans.tools.audit import AuditTool
from zwans.tools.base import Asker, Tool, ToolContext
from zwans.tools.bash import BashOutputTool, BashTool, KillBashTool
from zwans.tools.benchmark import BenchmarkTool
from zwans.tools.bisect import BisectTool
from zwans.tools.browser import BrowserTool
from zwans.tools.browser import available as browser_available
from zwans.tools.chart import ChartTool
from zwans.tools.ci import CITool
from zwans.tools.ci import available as ci_available
from zwans.tools.containers import ContainersTool
from zwans.tools.containers import available as containers_available
from zwans.tools.cron import CronTool
from zwans.tools.data import DataTool
from zwans.tools.database import DatabaseTool
from zwans.tools.diagnostics import DiagnosticsTool
from zwans.tools.docs import DocsTool
from zwans.tools.edit import EditTool
from zwans.tools.env_vars import EnvTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.history import HistoryTool
from zwans.tools.http import HttpTool
from zwans.tools.image_diff import ImageDiffTool
from zwans.tools.imports import ImportsTool
from zwans.tools.logs import LogsTool
from zwans.tools.memory import MemoryTool, read_notes
from zwans.tools.multi_edit import MultiEditTool
from zwans.tools.notebook_edit import NotebookEditTool
from zwans.tools.notify import NotifyTool
from zwans.tools.notify import available as notify_available
from zwans.tools.on_demand import with_search
from zwans.tools.openapi import OpenAPITool
from zwans.tools.outline import OutlineTool
from zwans.tools.packages import PackagesTool
from zwans.tools.ports import PortsTool
from zwans.tools.ports import available as ports_available
from zwans.tools.profile import ProfileTool
from zwans.tools.python_session import PythonTool
from zwans.tools.read import ReadTool
from zwans.tools.refs import ReferencesTool, RenameTool
from zwans.tools.run_tests import RunTestsTool
from zwans.tools.show_changes import ShowChangesTool
from zwans.tools.skill import SkillTool
from zwans.tools.task import TaskTool
from zwans.tools.todo import TodoWriteTool
from zwans.tools.video import VideoTool
from zwans.tools.web_local import WebFetchTool, WebSearchTool
from zwans.tools.write import WriteTool
from zwans.transcript import TranscriptWriter

type PolicyLoader = Callable[[Path, Path, Mode | None], LoadedPolicy]
type ProviderFactory = Callable[[Config, str], Provider]

CHATS = "chats"  # in Zwans's home: one empty folder per chat


def is_chat(workspace: str | Path, home: Path) -> bool:
    """Whether a session working in `workspace` is a chat."""
    return Path(workspace).parent == (home / CHATS).resolve()


@dataclass
class OpenedSession:
    config: Config
    info: SessionInfo
    session: Session
    executor: LocalExecutor
    meter: CostMeter
    transcript: TranscriptWriter
    store: SessionStore
    policy: LoadedPolicy
    model: str
    mcp: McpServers | None = None
    jobs: BackgroundJobs | None = None  # commands left running in the background
    checkpoints: Checkpoints | None = None  # the files before each turn, for /undo
    recorder: SessionRecorder | None = None  # what saves it, which keeps its title
    instructions: list[Path] = field(default_factory=list)  # instruction files, for a new one
    chat: bool = False  # no project and no tools of Zwans's own
    resumed: bool = False
    repaired: bool = False  # its last turn was cut off mid-tool
    had_turns: bool = False  # it had turns before, even if a rewind has dropped them all
    budget: Budget | None = None  # its spending cap, which /budget changes

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def empty(self) -> bool:
        """Nothing was ever said in it, so closing it deletes it rather than keep a blank row.
        One rewound to before its first turn is kept, as its row records what those turns cost."""
        return not self.session.messages and not self.had_turns

    async def start(self) -> tuple[list[McpTool], list[str]]:
        """Start the container, if commands run in one, and the MCP servers. Returns the MCP
        tools added and a message for each server that didn't start. Raises DockerError."""
        if isinstance(self.executor, DockerExecutor):
            await self.executor.start()
        if self.mcp is None:
            return [], []
        tools, problems = await self.mcp.start()
        self.session.tools.extend(tools)
        return tools, problems

    async def close(self) -> None:
        if self.jobs is not None:
            await self.jobs.close()
        for tool in self.session.tools:  # a tool with something left running, as Python has
            stop = getattr(tool, "aclose", None)
            if callable(stop):
                await stop()
        if self.mcp is not None:
            await self.mcp.close()
        if isinstance(self.executor, DockerExecutor):
            await self.executor.stop()
        await self.session.provider.aclose()
        self.transcript.close()
        if self.empty:
            self.store.delete(self.info.id)
            if self.chat:
                with contextlib.suppress(OSError):
                    Path(self.info.workspace).rmdir()  # its folder was only ever a placeholder
        self.store.close()


def open_session(
    config: Config,
    env: Mapping[str, str],
    *,
    workspace: Path,
    resume: str | None = None,
    rewind: int | None = None,
    model: str | None = None,
    mode: Mode | None = None,
    approver: Approver | None = None,
    listeners: Sequence[Callable[[Event], None]] = (),
    policy_loader: PolicyLoader = load_policy,
    make_provider: ProviderFactory | None = None,
    fake_script: Path | None = None,
    chat: bool = False,
    asker: Asker | None = None,
    ask_later: bool = False,
) -> OpenedSession:
    """A new session in `workspace`, a new chat (`chat`, which ignores `workspace`), or the
    saved one `resume` names. Raises ConfigError (JailError among them), SessionError or
    PolicyError. Call `start()` before the first turn.

    `asker` puts the model's questions to the person, which gives it the AskUser tool.
    `ask_later` gives it the tool with the asker still to come, as the server's is."""
    model = canonical(model) if model else None
    store = SessionStore(config.home / "sessions.db")
    messages: list[Message] = []
    repaired = False
    followed: list[Path] = []
    unsaved_model: str | None = None
    had_turns = False
    if resume is not None:
        try:
            found = store.get(resume)
            if is_chat(found.workspace, config.home):
                Path(found.workspace).mkdir(parents=True, exist_ok=True)  # nothing was in it
            if not Path(found.workspace).is_dir():  # checked first, so nothing is rewound
                raise SessionError(
                    f"Session {found.id} worked in {found.workspace}, which no longer exists. "
                    "Move the folder back to resume it."
                )
            # Counted before the rewind. A session rewound to before turn 1 keeps the title
            # its first prompt gave it, so it still counts when resumed again later.
            had_turns = found.turns > 0 or bool(found.title)
            info, messages, repaired = load_session(store, found.id, rewind)
        except SessionError:
            store.close()  # the server carries on after a failed resume
            raise
        if model and model != info.model and is_known(model):
            store.set_model(info.id, model)  # --model switches it, as /model does
            info.model = model
        elif model and model != info.model:
            # A name Zwans doesn't know may be a typo, which would 404 on every later resume
            # too. It's saved once a reply from it comes in.
            unsaved_model = model
        meter = CostMeter.restore(info.usage)
        skills = find_skills(
            skill_folders(Path(info.workspace), config.home, config.builtin_skills)
        )
    else:
        session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        root = (config.home / CHATS / session_id if chat else workspace).resolve()
        skills = find_skills(skill_folders(root, config.home, config.builtin_skills))
        instructions = load_instructions(root, config.home)  # for a chat, only the user's own
        followed = [path for path, _ in instructions]
        notes = read_notes(config.home, root) if "Memory" not in config.disabled_tools else []
        if chat:
            system = chat_prompt(instructions, config.web)
        elif config.executor == "docker":
            system = system_prompt(
                root, "bash", instructions, SANDBOX_OS, skills, config.web, notes
            )
        elif config.executor == "jail":
            system = system_prompt(root, "bash", instructions, JAIL_OS, skills, config.web, notes)
        elif config.executor == "seatbelt":
            shell = describe_shell(config.shell)
            system = system_prompt(
                root, shell, instructions, SEATBELT_OS, skills, config.web, notes
            )
        else:
            shell = describe_shell(config.shell)
            system = system_prompt(
                root, shell, instructions, skills=skills, web=config.web, notes=notes
            )
        info = SessionInfo(
            id=session_id, workspace=str(root), model=model or config.model, system=system
        )
        meter = CostMeter()
    model = model or info.model

    provider: Provider
    if make_provider is not None:
        provider = make_provider(config, model)
    elif fake_script is not None:
        provider = FakeProvider.from_file(fake_script)
    else:
        try:
            provider = ModelRouter(config, env, model)  # checks the model's provider and key
            # The models work is handed to, checked now rather than at the first subagent.
            helper(provider, config.subagent_model)
            helper(provider, config.compact_model)
        except ConfigError:
            store.close()
            raise
    if resume is None:
        store.create(info)  # only once the credential is known to be there

    root = Path(info.workspace)
    chat = is_chat(root, config.home)  # a resumed chat is still one
    if chat:
        root.mkdir(parents=True, exist_ok=True)
    loaded = policy_loader(root, config.home, mode)
    policy = loaded.policy
    transcript = TranscriptWriter(config.home / "transcripts" / f"{info.id}.jsonl")
    if resume is not None and rewind is not None:
        # The transcript only grows, so it says where the conversation now ends; the web UI
        # leaves out the turns after it when it shows the session.
        transcript.on_event(Rewound(turn=rewind))
    spill_dir = config.home / "tool-output" / info.id
    executor: LocalExecutor
    if chat:  # nothing runs in a chat, so there's no container or jail to start
        executor = LocalExecutor(root, shell=config.shell, spill_dir=spill_dir)
    elif config.executor == "docker":
        executor = DockerExecutor(root, spill_dir=spill_dir)
    elif config.executor == "jail":
        executor = JailExecutor(root, spill_dir=spill_dir)
    elif config.executor == "seatbelt":
        executor = SeatbeltExecutor(root, shell=config.shell, spill_dir=spill_dir)
    else:
        executor = LocalExecutor(root, shell=config.shell, spill_dir=spill_dir)
    jobs = BackgroundJobs(executor)
    permissions = Permissions(
        policy,
        inside=executor.contains,
        relative=executor.relative,
        approver=approver,
        root=executor.root,
    )
    tools: list[Tool[Any]] = []
    changes: ShowChangesTool | None = None
    if not chat:
        tools = [
            ReadTool(),
            WriteTool(),
            EditTool(),
            GlobTool(),
            GrepTool(hidden=policy.hidden_from_search),
            OutlineTool(hidden=policy.hidden_from_search),
            ReferencesTool(),
            RenameTool(root),
            BashTool(),
            BashOutputTool(),
            KillBashTool(),
            RunTestsTool(root, config.test_commands),
        ]
        if config.multi_edit:
            tools.insert(3, MultiEditTool())  # next to Edit
        if config.diagnostics:
            own = config.diagnostics if isinstance(config.diagnostics, list) else ()
            tools.append(DiagnosticsTool(root, own))
        tools.append(DocsTool())
        if config.video and shutil.which("ffprobe") and shutil.which("ffmpeg"):
            tools.append(VideoTool())
        tools += [NotebookEditTool(), LogsTool(), DatabaseTool(), DataTool(), ImageDiffTool()]
        tools += [ArchiveTool(), ImportsTool(), OpenAPITool(), CronTool()]
        tools += [HistoryTool(), BisectTool(), ProfileTool(), BenchmarkTool(), HttpTool()]
        tools += [EnvTool(hidden=policy.hidden_from_search), AuditTool()]
        # These run a program of the machine's (lsof, docker, gh, osascript) when it's there.
        if ports_available():
            tools.append(PortsTool())
        if containers_available():
            tools.append(ContainersTool())
        if ci_available():
            tools.append(CITool())
        if notify_available():
            tools.append(NotifyTool())
        if config.browser and browser_available():
            tools.append(BrowserTool())
        if executor.interactive:
            tools.append(PythonTool())
        if config.checkpoints:
            changes = ShowChangesTool(None)  # given the checkpoints once they exist, below
            tools.append(changes)
        tools.append(MemoryTool(config.home, root))
        if asker is not None or ask_later:
            tools.append(AskUserTool())
        if config.todos:
            tools.append(TodoWriteTool())
        if skills:
            tools.append(SkillTool(skills))
        if config.subagents:
            tools.append(TaskTool(config.subagent_max_steps))
    # Charts are drawn in the web UI, for a session or a chat; the terminal gets their summary.
    tools.append(ChartTool())
    if config.web:
        # For models whose provider has no web tools of its own; a chat gets them too. With
        # Claude's own turned on, the router leaves these out (providers/router.py).
        tools.append(WebFetchTool())
        tools.append(PackagesTool())
        search = config.web_search
        if search is not None and WebSearchTool.problem(search, env) is None:
            tools.append(WebSearchTool(search, env))
    if chat:
        # A chat can run Python only where there's a sandbox to hold it: on a Mac.
        with contextlib.suppress(SeatbeltError):
            tools.append(PythonTool(sandbox=SeatbeltExecutor(root, spill_dir=spill_dir)))
    tools = [tool for tool in tools if tool.name not in config.disabled_tools]
    if config.tools_on_demand and not chat:  # a chat has only a few
        tools = with_search(tools, config.always_tools)
    session = Session(
        provider=provider,
        tools=tools,
        ctx=ToolContext(executor=executor, jobs=jobs, ask=asker),
        system=info.system,  # a resumed session keeps the exact prompt it started with
        listeners=[*listeners, transcript.on_event, meter.on_event],
        max_steps=config.max_steps,
        compactor=Compactor(
            provider,
            config.compact_at,
            config.keep_messages,
            summarizer=helper(provider, config.compact_model),
        ),
        permissions=permissions,
        # Hooks are about tools and a project's checks, and a chat has neither.
        hooks=Hooks(policy.hooks, root) if policy.hooks and not chat else None,
        follow_through=follow_through_for(config, provider),
        subagent_provider=helper(provider, config.subagent_model),
    )
    session.messages = messages
    session.turn = info.turns
    checkpoints = None
    if config.checkpoints and not chat:  # a chat has no files to put back
        checkpoints = Checkpoints(root, config.home, info.id)
        session.before_turn = checkpoints.save
        if changes is not None:
            changes.checkpoints = checkpoints
    saved = len(messages) - (1 if repaired else 0)
    recorder = SessionRecorder(store, info.id, session, meter, saved=saved, title=info.title)
    session.listeners.append(recorder.on_event)
    if unsaved_model is not None:
        session.listeners.append(_ModelSaver(store, info, provider, unsaved_model).on_event)
    recorder.save()  # saves the answers to any cut-off tool calls right away
    budget = Budget(meter, config.budget)
    session.limit = budget.exceeded

    mcp = None
    if config.mcp_servers and not chat:
        mcp = McpServers(config.mcp_servers, root, env, config.home / "mcp-logs")
    return OpenedSession(
        config=config,
        info=info,
        session=session,
        executor=executor,
        meter=meter,
        budget=budget,
        transcript=transcript,
        store=store,
        policy=loaded,
        model=model,
        mcp=mcp,
        jobs=jobs,
        checkpoints=checkpoints,
        recorder=recorder,
        instructions=followed,
        chat=chat,
        resumed=resume is not None,
        repaired=repaired,
        had_turns=had_turns,
    )


class _ModelSaver:
    """Saves a model with the session once a reply from it has come in, so it's known to work."""

    def __init__(
        self, store: SessionStore, info: SessionInfo, provider: Provider, model: str
    ) -> None:
        self.store = store
        self.info = info
        self.provider = provider
        self.model: str | None = model

    def on_event(self, event: Event) -> None:
        if self.model is None or not isinstance(event, ModelCalled) or event.purpose != "turn":
            return
        # Unless /model has switched to another since, which it saved itself.
        if getattr(self.provider, "model", self.model) == self.model:
            self.store.set_model(self.info.id, self.model)
            self.info.model = self.model
        self.model = None


def describe_shell(configured: str | None) -> str:
    try:
        return configured or find_bash()
    except FileNotFoundError:
        return "none found, so the Bash tool will fail"
