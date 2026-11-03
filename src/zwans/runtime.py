"""Opens a session with everything it needs, for the CLI and the server alike: the model,
the executor, the policy, the tools, the transcript, and the saved copy in sessions.db."""

import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from zwans.config import Config, load_credential
from zwans.context.compaction import Compactor
from zwans.context.instructions import load_instructions
from zwans.events import Event
from zwans.executor.docker import SANDBOX_OS, DockerExecutor
from zwans.executor.local import LocalExecutor, find_bash
from zwans.ext.hooks import Hooks
from zwans.ext.skills import find_skills, skill_folders
from zwans.mcp.tools import McpServers, McpTool
from zwans.messages import Message
from zwans.policy.engine import Approver, Permissions
from zwans.policy.rules import LoadedPolicy, Mode, load_policy
from zwans.pricing import CostMeter
from zwans.prompt import system_prompt
from zwans.providers.anthropic import AnthropicProvider
from zwans.providers.base import Provider
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.store import SessionInfo, SessionRecorder, SessionStore, load_session
from zwans.tools.base import Tool, ToolContext
from zwans.tools.bash import BashTool
from zwans.tools.edit import EditTool
from zwans.tools.glob import GlobTool
from zwans.tools.grep import GrepTool
from zwans.tools.read import ReadTool
from zwans.tools.skill import SkillTool
from zwans.tools.task import TaskTool
from zwans.tools.write import WriteTool
from zwans.transcript import TranscriptWriter

type PolicyLoader = Callable[[Path, Path, Mode | None], LoadedPolicy]
type ProviderFactory = Callable[[Config, str], Provider]


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
    instructions: list[Path] = field(default_factory=list)  # ZWANS.md files, for a new one
    resumed: bool = False
    repaired: bool = False  # its last turn was cut off mid-tool

    @property
    def id(self) -> str:
        return self.info.id

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
        if self.mcp is not None:
            await self.mcp.close()
        if isinstance(self.executor, DockerExecutor):
            await self.executor.stop()
        await self.session.provider.aclose()
        self.transcript.close()
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
) -> OpenedSession:
    """A new session in `workspace`, or the saved one `resume` names. Raises ConfigError,
    SessionError or PolicyError. Call `start()` before the first turn."""
    store = SessionStore(config.home / "sessions.db")
    messages: list[Message] = []
    repaired = False
    followed: list[Path] = []
    if resume is not None:
        info, messages, repaired = load_session(store, resume, rewind)
        meter = CostMeter.restore(info.usage)
        skills = find_skills(skill_folders(Path(info.workspace), config.home))
    else:
        root = workspace.resolve()
        skills = find_skills(skill_folders(root, config.home))
        instructions = load_instructions(root, config.home)
        followed = [path for path, _ in instructions]
        if config.executor == "docker":
            system = system_prompt(root, "bash", instructions, SANDBOX_OS, skills)
        else:
            shell = describe_shell(config.shell)
            system = system_prompt(root, shell, instructions, skills=skills)
        session_id = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        info = SessionInfo(id=session_id, workspace=str(root), model=config.model, system=system)
        meter = CostMeter()
    model = model or info.model

    provider: Provider
    if make_provider is not None:
        provider = make_provider(config, model)
    elif fake_script is not None:
        provider = FakeProvider.from_file(fake_script)
    else:
        credential = load_credential(config, env)
        provider = AnthropicProvider(credential, model, config.effort, config.max_tokens)
    if resume is None:
        store.create(info)  # only once the credential is known to be there

    root = Path(info.workspace)
    loaded = policy_loader(root, config.home, mode)
    policy = loaded.policy
    transcript = TranscriptWriter(config.home / "transcripts" / f"{info.id}.jsonl")
    spill_dir = config.home / "tool-output" / info.id
    executor: LocalExecutor
    if config.executor == "docker":
        executor = DockerExecutor(root, spill_dir=spill_dir)
    else:
        executor = LocalExecutor(root, shell=config.shell, spill_dir=spill_dir)
    permissions = Permissions(
        policy, inside=executor.contains, relative=executor.relative, approver=approver
    )
    tools: list[Tool[Any]] = [
        ReadTool(),
        WriteTool(),
        EditTool(),
        GlobTool(),
        GrepTool(),
        BashTool(),
    ]
    if skills:
        tools.append(SkillTool(skills))
    if config.subagents:
        tools.append(TaskTool(config.subagent_max_steps))
    session = Session(
        provider=provider,
        tools=tools,
        ctx=ToolContext(executor=executor),
        system=info.system,  # a resumed session keeps the exact prompt it started with
        listeners=[*listeners, transcript.on_event, meter.on_event],
        max_steps=config.max_steps,
        compactor=Compactor(provider, config.compact_at, config.keep_messages),
        permissions=permissions,
        hooks=Hooks(policy.hooks, root) if policy.hooks else None,
    )
    session.messages = messages
    session.turn = info.turns
    saved = len(messages) - (1 if repaired else 0)
    recorder = SessionRecorder(store, info.id, session, meter, saved=saved, title=info.title)
    session.listeners.append(recorder.on_event)
    recorder.save()  # saves the answers to any cut-off tool calls right away

    mcp = None
    if config.mcp_servers:
        mcp = McpServers(config.mcp_servers, root, env, config.home / "mcp-logs")
    return OpenedSession(
        config=config,
        info=info,
        session=session,
        executor=executor,
        meter=meter,
        transcript=transcript,
        store=store,
        policy=loaded,
        model=model,
        mcp=mcp,
        instructions=followed,
        resumed=resume is not None,
        repaired=repaired,
    )


def describe_shell(configured: str | None) -> str:
    try:
        return configured or find_bash()
    except FileNotFoundError:
        return "none found, so the Bash tool will fail"
