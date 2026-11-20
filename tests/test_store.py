import asyncio
from pathlib import Path
from typing import Any

import pytest
from helpers import user

from zwans.config import Config
from zwans.events import ContextCompacted, Event, ToolCallRequested
from zwans.loop import STOPPED
from zwans.messages import Message, RawBlock, TextBlock, ToolResultBlock, ToolUseBlock
from zwans.pricing import CostMeter
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.runtime import OpenedSession, open_session
from zwans.session import Session
from zwans.store import (
    SessionError,
    SessionInfo,
    SessionRecorder,
    SessionStore,
    load_session,
    title_of,
)
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


def test_a_turn_that_fails_before_any_reply_is_taken_back(tmp_path: Path, ctx: ToolContext) -> None:
    """A rate limit or a wrong model name: the prompt mustn't be sent again with the next."""
    store = SessionStore(tmp_path / "sessions.db")
    provider = FakeProvider([])  # an empty script fails like an API error
    session = new_session(store, provider, ctx)

    assert asyncio.run(session.send("Reply with just the word hi.")) == "error"

    assert session.turn == 0 and session.messages == []
    assert store.load_messages("s1") == []
    assert (store.get("s1").turns, store.get("s1").title) == (0, "")

    provider._script.append(reply("hello"))
    asyncio.run(session.send("Reply with just the word hello."))

    asked = Message(role="user", content=[TextBlock(text="Reply with just the word hello.")])
    assert provider.requests[-1] == [asked.model_copy(update={"turn": 1})]
    saved = store.get("s1")
    assert (saved.turns, saved.title) == (1, "Reply with just the word hello.")


def test_a_turn_that_fails_after_a_reply_still_counts_with_its_cost(
    tmp_path: Path, ctx: ToolContext
) -> None:
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    read = ToolUseBlock(id="call_1", name="Read", input={"path": "notes.txt"})
    first = ModelResponse(
        content=[read], stop_reason="tool_use", model="claude-opus-5-5", input_tokens=1_000
    )
    store = SessionStore(tmp_path / "sessions.db")
    session = new_session(store, FakeProvider([first]), ctx)  # the second call fails

    assert asyncio.run(session.send("What does notes.txt say?")) == "error"

    saved = store.get("s1")
    assert session.turn == 1 and saved.turns == 1
    assert saved.title == "What does notes.txt say?"
    assert saved.usage["dollars"] == pytest.approx(0.004)
    assert len(store.load_messages("s1")) == 3  # the prompt, the call, and its result


def test_counts_are_saved_while_the_turn_runs(tmp_path: Path, ctx: ToolContext) -> None:
    """So a session killed mid-turn keeps that turn, can rewind it, and knows what it cost."""
    read = ToolUseBlock(id="call_1", name="Read", input={"path": "notes.txt"})
    first = ModelResponse(
        content=[read], stop_reason="tool_use", model="claude-opus-5-5", input_tokens=1_000
    )
    store = SessionStore(tmp_path / "sessions.db")
    session = new_session(store, FakeProvider([first, reply("Done.")]), ctx)
    seen: list[SessionInfo] = []

    def look(event: Event) -> None:
        if isinstance(event, ToolCallRequested):
            seen.append(store.get("s1"))

    session.listeners.append(look)
    asyncio.run(session.send("Read notes.txt"))

    [mid_turn] = seen
    assert mid_turn.turns == 1 and mid_turn.title == "Read notes.txt"
    assert mid_turn.usage["dollars"] == pytest.approx(0.004)


def test_a_session_saved_mid_turn_by_an_older_version_counts_that_turn(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    store.create(SessionInfo(id="s1", workspace="/work", model="m", system="S"))
    store.append_messages("s1", 0, [Message(role="user", content=[TextBlock(text="Hi")], turn=1)])

    assert store.get("s1").turns == 1
    assert [info.turns for info in store.recent()] == [1]


def test_empty_sessions_are_not_listed_and_can_be_deleted(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    for session_id in ("empty", "used"):
        store.create(SessionInfo(id=session_id, workspace="/w", model="m", system="S"))
    store.append_messages("used", 0, [user("Hi")])

    assert [info.id for info in store.recent()] == ["used"]
    store.delete("used")
    assert store.recent() == []
    assert store.load_messages("used") == []


def test_rewinding_to_a_turn_the_session_doesnt_have_is_refused(
    tmp_path: Path, ctx: ToolContext
) -> None:
    store = SessionStore(tmp_path / "sessions.db")
    session = new_session(store, FakeProvider([reply("One."), reply("Two.")]), ctx)
    for prompt in ("First", "Second"):
        asyncio.run(session.send(prompt))

    for turn in (2, 9):
        with pytest.raises(SessionError, match="has 2 turns, so there are no turns after"):
            store.rewind("s1", turn)
    assert store.get("s1").turns == 2


def test_titles_are_one_short_line_without_the_mentioned_files() -> None:
    mentioned = "\n\nThe files I mentioned, as they are now:\n\npkg/stats.py\n```\nx = 1\n```"
    assert title_of(f"What does @pkg/stats.py do?{mentioned}") == "What does @pkg/stats.py do?"
    assert title_of("  Fix the\n   tests  ") == "Fix the tests"
    long = "Run the tests with `python -m pytest` and then summarize every failure " * 2
    title = title_of(long)
    assert len(title) <= 80 and title.endswith("…")
    assert long.startswith(title[:-1]) and title[-2] != " "


def open_fake(tmp_path: Path, workspace: Path, replies: list[str], **kwargs: Any) -> OpenedSession:
    script = [reply(text) for text in replies]
    return open_session(
        Config(home=tmp_path / "home", checkpoints=False),
        {},
        workspace=workspace,
        mode="auto",
        make_provider=lambda config, model: FakeProvider(script),
        **kwargs,
    )


def test_an_empty_session_is_deleted_when_it_closes(tmp_path: Path) -> None:
    unused = open_fake(tmp_path, tmp_path, [])
    asyncio.run(unused.close())
    used = open_fake(tmp_path, tmp_path, ["Hi."])
    asyncio.run(used.session.send("Hi"))
    asyncio.run(used.close())

    store = SessionStore(tmp_path / "home" / "sessions.db")
    assert [info.id for info in store.recent()] == [used.id]
    with pytest.raises(SessionError):
        store.get(unused.id)


def test_the_model_chosen_for_a_session_is_saved_with_it(tmp_path: Path) -> None:
    first = open_fake(tmp_path, tmp_path, ["Hi."], model="claude-haiku-4-5")
    asyncio.run(first.session.send("Hi"))
    asyncio.run(first.close())

    resumed = open_fake(tmp_path, tmp_path, [], resume=first.id)
    asyncio.run(resumed.close())
    switched = open_fake(tmp_path, tmp_path, [], resume=first.id, model="claude-sonnet-5-5")
    asyncio.run(switched.close())
    again = open_fake(tmp_path, tmp_path, [], resume=first.id)
    asyncio.run(again.close())

    assert resumed.model == "claude-haiku-4-5"
    assert switched.model == again.model == "claude-sonnet-5-5"


def test_an_unknown_model_is_saved_only_once_it_has_replied(tmp_path: Path) -> None:
    first = open_fake(tmp_path, tmp_path, ["Hi."], model="claude-haiku-4-5")
    asyncio.run(first.session.send("Hi"))
    asyncio.run(first.close())
    store = SessionStore(tmp_path / "home" / "sessions.db")

    # A typo: its turn fails, so the session keeps the model it had.
    typo = open_fake(tmp_path, tmp_path, [], resume=first.id, model="nope")
    asyncio.run(typo.session.send("Again"))
    asyncio.run(typo.close())
    assert typo.model == "nope"
    assert store.get(first.id).model == "claude-haiku-4-5"

    # A newer model Zwans has no price for yet works, so it's kept.
    newer = open_fake(tmp_path, tmp_path, ["Hello."], resume=first.id, model="claude-opus-9-0")
    assert store.get(first.id).model == "claude-haiku-4-5"
    asyncio.run(newer.session.send("Again"))
    asyncio.run(newer.close())
    assert store.get(first.id).model == "claude-opus-9-0"


def test_resuming_a_session_whose_folder_is_gone_says_so(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    first = open_fake(tmp_path, workspace, ["Hi.", "Two."])
    asyncio.run(first.session.send("Hi"))
    asyncio.run(first.session.send("Again"))
    asyncio.run(first.close())
    workspace.rename(tmp_path / "moved")

    with pytest.raises(SessionError, match="which no longer exists"):
        open_fake(tmp_path, tmp_path, [], resume=first.id, rewind=1)

    store = SessionStore(tmp_path / "home" / "sessions.db")
    assert store.get(first.id).turns == 2  # nothing was rewound
