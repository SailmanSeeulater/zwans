"""Work handed to another model: subagents on subagent_model, handoff notes on compact_model,
while the session's own model keeps the conversation."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from helpers import user
from test_subagents import Recording, say, task, use

from zwans.config import Config, ConfigError, ProviderConfig
from zwans.context.compaction import Compactor
from zwans.executor.local import LocalExecutor
from zwans.messages import Message, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.catalog import ModelError, Resolved
from zwans.providers.fake import FakeProvider
from zwans.providers.router import ModelRouter, helper
from zwans.runtime import open_session
from zwans.session import Session
from zwans.tools.base import ToolContext
from zwans.tools.task import TaskTool

KEY = {"ANTHROPIC_API_KEY": "sk-test"}


class Backend(FakeProvider):
    closed = False

    async def aclose(self) -> None:
        self.closed = True


def backends() -> tuple[Any, list[Backend]]:
    made: list[Backend] = []

    def make(resolved: Resolved) -> Backend:
        made.append(Backend([ModelResponse(content=[], stop_reason="end_turn")]))
        return made[-1]

    return make, made


def test_a_helper_router_stays_on_its_model_whatever_the_session_switches_to() -> None:
    make, made = backends()
    router = ModelRouter(Config(), KEY, "claude-opus-5-5", make_backend=make)

    assert router.helper(None) is router
    haiku = router.helper("claude-haiku-5-5")
    assert haiku is not router and haiku.model == "claude-haiku-5-5"
    assert router.helper("anthropic/claude-haiku-5-5") is haiku  # one per model

    router.set_model("claude-sonnet-5-5")
    assert haiku.model == "claude-haiku-5-5"
    assert made[0].model == "claude-sonnet-5-5" and made[1].model == "claude-haiku-5-5"

    with pytest.raises(ModelError):
        router.helper("openrouter/x")  # no key

    asyncio.run(router.aclose())
    assert all(backend.closed for backend in made)


def test_a_provider_that_doesnt_route_is_its_own_helper() -> None:
    scripted = FakeProvider([])

    assert helper(scripted, "claude-haiku-5-5") is scripted


def test_subagents_run_on_the_subagent_provider(tmp_path: Path) -> None:
    main = Recording([use(("t1", "Task", task("Find the loader."))), say("Found it.")])
    cheap = Recording([say("config.py, load_config().")])
    s = Session(
        provider=main,
        tools=[TaskTool()],
        ctx=ToolContext(executor=LocalExecutor(tmp_path)),
        system="You are Zwans.",
        listeners=[],
        subagent_provider=cheap,
    )

    assert asyncio.run(s.send("Where is the config loaded?")) == "end_turn"

    assert len(main.requests) == 2 and len(cheap.requests) == 1
    assert cheap.requests[0] == [Message(role="user", content=[TextBlock(text="Find the loader.")])]
    [result] = [b for m in s.messages for b in m.content if isinstance(b, ToolResultBlock)]
    assert result.content == "config.py, load_config()."


def test_without_a_subagent_provider_subagents_use_the_sessions(tmp_path: Path) -> None:
    s = Session(
        provider=FakeProvider([]),
        tools=[],
        ctx=ToolContext(executor=LocalExecutor(tmp_path)),
        system="",
        listeners=[],
    )

    assert s.subagent_provider is s.provider


def test_the_notes_come_from_the_summarizer_and_the_threshold_from_the_session() -> None:
    config = Config(providers={"ollama": ProviderConfig(context_window=10_000)})
    make, _ = backends()
    session_model = ModelRouter(config, KEY, "ollama/qwen3:8b", make_backend=make)
    notes = FakeProvider([say("The notes.")])
    compactor = Compactor(session_model, threshold=200_000, keep_messages=1, summarizer=notes)
    call = ToolUseBlock(id="c1", name="Read", input={"path": "a.py"})
    messages = [
        user("Fix it"),
        Message(role="assistant", content=[call]),
        user("ok"),
        Message(role="assistant", content=[TextBlock(text="Done.")]),
    ]

    asyncio.run(compactor.compact(messages))

    assert compactor.threshold == 8_000  # 80% of the session model's context, not the notes'
    assert len(notes.requests) == 1
    assert "The notes." in str(messages[0].content[0])


def test_a_session_with_a_helper_model_it_cant_use_doesnt_open(tmp_path: Path) -> None:
    config = Config(home=tmp_path / "home", subagent_model="openrouter/x")

    with pytest.raises(ConfigError, match="OPENROUTER_API_KEY"):
        open_session(config, KEY, workspace=tmp_path)
