import asyncio
from pathlib import Path

import pytest
from helpers import user

from zwans.events import ContextCompacted
from zwans.loop import STOPPED
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.pricing import CostMeter
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.session import Session
from zwans.store import SessionError, SessionInfo, SessionRecorder, SessionStore, load_session
from zwans.tools.base import ToolContext
from zwans.tools.read import ReadTool

THINKING = RawBlock(type="thinking", data={"type": "thinking", "thinking": "", "signature": "s"})


def new_session(
    store: SessionStore, provider: FakeProvider, ctx: ToolContext, session_id: str = "s1"
) -> Session:
    info = SessionInfo(id=session_id, workspace="/work", model="m", system="You are Zwans.")
    store.create(info)
    meter = CostMeter()
    session = Session(provider, [ReadTool()], ctx, info.system, listeners=[meter.on_event])
    session.listeners.append(SessionRecorder(store, info.id, session, meter).on_event)
    return session


def resumed_session(
    store: SessionStore, provider: FakeProvider, ctx: ToolContext, rewind_to: int | None = None
) -> tuple[Session, bool]:
    info, messages, repaired = load_session(store, "s1", rewind_to)
    session = Session(provider, [ReadTool()], ctx, info.system, listeners=[])
    session.messages = messages
    session.turn = info.turns
    return session, repaired


def reply(text: str) -> ModelResponse:
    return ModelResponse(content=[THINKING, TextBlock(text=text)], stop_reason="end_turn")


def test_resume_restores_the_session_exactly(tmp_path: Path, ctx: ToolContext) -> None:
    """Phase 2's "Done when": the next request after a resume is the one Zwans would have sent."""
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    read = ToolUseBlock(id="call_1", name="Read", input={"path": "notes.txt"})
    store = SessionStore(tmp_path / "sessions.db")
    first = new_session(
        store,
        FakeProvider(
            [
                ModelResponse(content=[THINKING, read], stop_reason="tool_use"),
                reply("It says hello."),
                reply("Second answer."),
            ]
        ),
        ctx,
    )
    asyncio.run(first.send("What does notes.txt say?"))
    asyncio.run(first.send("And again?"))

    later = FakeProvider([reply("Third answer.")])
    resumed, repaired = resumed_session(store, later, ctx)
    asyncio.run(resumed.send("Once more?"))

    assert not repaired
    assert resumed.system == first.system
    assert resumed.turn == 3
    assert later.requests[0][:-1] == first.messages  # thinking blocks and all, byte for byte
    assert store.get("s1").title == "What does notes.txt say?"


def test_resume_answers_tool_calls_left_running(tmp_path: Path, ctx: ToolContext) -> None:
    """If Zwans was killed mid-tool, the saved session ends with an unanswered tool call."""
    store = SessionStore(tmp_path / "sessions.db")
    store.create(SessionInfo(id="s1", workspace="/work", model="m", system="S"))
    call = ToolUseBlock(id="call_1", name="Bash", input={"command": "sleep 100"})
    cut_off = [
        Message(role="user", content=[TextBlock(text="Wait")], turn=1),
        Message(role="assistant", content=[THINKING, call], turn=1),
    ]
    store.append_messages("s1", 0, cut_off)

    resumed, repaired = resumed_session(store, FakeProvider([]), ctx)

    assert repaired
    assert resumed.messages[:2] == cut_off
    assert resumed.messages[2].content == [
        ToolResultBlock(tool_use_id="call_1", content=STOPPED, is_error=True)
    ]


def test_rewind_drops_later_turns(tmp_path: Path, ctx: ToolContext) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    replies = FakeProvider([reply("One."), reply("Two."), reply("Three.")])
    session = new_session(store, replies, ctx)
    for prompt in ("First", "Second", "Third"):
        asyncio.run(session.send(prompt))

    resumed, _ = resumed_session(store, FakeProvider([]), ctx, rewind_to=1)

    assert resumed.turn == 1
    assert [m.turn for m in resumed.messages] == [1, 1]
    assert resumed.messages[0] == Message(role="user", content=[TextBlock(text="First")], turn=1)


def test_rewinding_past_a_compaction_is_refused(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    store.create(SessionInfo(id="s1", workspace="/work", model="m", system="S"))
    summary = Message(role="user", content=[TextBlock(text="[Summary] ...")], turn=5)
    store.append_messages("s1", 0, [summary])

    with pytest.raises(SessionError, match="earliest turn to rewind to is 5"):
        store.rewind("s1", 2)


def test_compaction_rewrites_the_saved_history(tmp_path: Path, ctx: ToolContext) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session = new_session(store, FakeProvider([reply("One."), reply("Two.")]), ctx)
    asyncio.run(session.send("First"))
    session.messages[:] = [user("[Summary] the first turn"), session.messages[-1]]
    recorder = session.listeners[-1]

    recorder(ContextCompacted(tokens_before=1_000, tokens_after=100))

    assert store.load_messages("s1") == session.messages


def test_sessions_are_found_by_the_start_of_their_id(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    for session_id in ("20261008-1200-aaaa", "20261008-1300-bbbb"):
        store.create(SessionInfo(id=session_id, workspace="/w", model="m", system="S"))

    assert store.get("20261008-13").id == "20261008-1300-bbbb"
    with pytest.raises(SessionError, match="2 sessions start with"):
        store.get("20261008")
