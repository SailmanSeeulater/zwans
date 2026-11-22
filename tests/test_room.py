import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from zwans.cli.app import app
from zwans.config import Config
from zwans.events import TextDelta
from zwans.messages import Message, TextBlock
from zwans.providers.base import ModelResponse, ProviderError, StreamItem
from zwans.providers.fake import FakeProvider
from zwans.room import (
    USER,
    AgentSpec,
    Line,
    LineAdded,
    Room,
    RoomError,
    RoomEvent,
    RoomInfo,
    RoomStopped,
    SpeakerText,
    check_agents,
    load_room,
    parse_agent,
    recent_rooms,
)
from zwans.server.app import ServerSettings, create_app
from zwans.tools.base import Tool

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ADA_BO_CY = [
    AgentSpec(name="Ada", model="m1"),
    AgentSpec(name="Bo", model="m2"),
    AgentSpec(name="Cy", model="m3"),
]


def reply(text: str, model: str = "claude-haiku-5-5", tokens: int = 1000) -> ModelResponse:
    return ModelResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        model=model,
        input_tokens=tokens,
        output_tokens=tokens,
    )


class Chunked:
    """Streams each reply in the pieces given, as a real provider would."""

    def __init__(self, *replies: list[str], wait: float = 0.0) -> None:
        self.replies = list(replies)
        self.wait = wait
        self.systems: list[str] = []
        self.requests: list[list[Message]] = []

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        self.systems.append(system)
        self.requests.append(list(messages))
        if not self.replies:
            raise ProviderError("no more replies")
        pieces = self.replies.pop(0)
        for piece in pieces:
            yield TextDelta(text=piece)
            if self.wait:
                await asyncio.sleep(self.wait)
        yield reply("".join(pieces))

    async def aclose(self) -> None:
        pass


def room_with(provider: Any, agents: Sequence[AgentSpec] = ADA_BO_CY, **kw: Any) -> Room:
    return Room.new("Tabs or spaces?", agents, lambda _model: provider, **kw)


def collect(room: Room, turns: int) -> list[RoomEvent]:
    async def go() -> list[RoomEvent]:
        return [event async for event in room.run(turns)]

    return asyncio.run(go())


def test_each_agent_sees_its_own_lines_as_its_turns_and_others_tagged() -> None:
    room = room_with(FakeProvider([]))
    room.info.lines = [
        Line(speaker="Ada", text="Tabs."),
        Line(speaker="Bo", text="Spaces."),
        Line(speaker=USER, text="Be nice."),
        Line(speaker="Ada", text="Fine.", cut=True),
    ]

    seen_by_bo = room.messages_for(room.agent("Bo"))
    seen_by_ada = room.messages_for(room.agent("Ada"))

    def texts(message: Message) -> list[str]:
        return [b.text for b in message.content if isinstance(b, TextBlock)]

    assert [m.role for m in seen_by_bo] == ["user", "assistant", "user"]
    assert texts(seen_by_bo[0]) == ["Topic: Tabs or spaces?", "[Ada]: Tabs."]
    assert texts(seen_by_bo[1]) == ["Spaces."]
    assert texts(seen_by_bo[2]) == ["[User]: Be nice.", "[Ada]: Fine. [cut off]"]
    # Ada spoke last, so her conversation still ends on a user message.
    assert [m.role for m in seen_by_ada] == ["user", "assistant", "user", "assistant", "user"]
    assert texts(seen_by_ada[-1]) == ["(Your turn again.)"]


def test_the_system_prompt_names_the_agent_the_others_and_the_topic() -> None:
    agents = [
        AgentSpec(name="Ada", model="m1", persona="a skeptic"),
        AgentSpec(name="Bo", model="m2"),
    ]
    system = room_with(FakeProvider([]), agents).system_for(agents[1])

    assert system.startswith("You are Bo.")
    assert "Tabs or spaces?" in system
    assert "- Ada (m1): a skeptic" in system
    assert "@Name" in system


def test_agents_take_turns_and_a_mention_goes_next_without_skipping_anyone() -> None:
    room = room_with(FakeProvider([]))
    order = []
    for text in ["Hi", "@Cy you?", "Me.", "Hm.", "Ok."]:
        speaker = room.next_speaker().name
        order.append(speaker)
        room.info.lines.append(Line(speaker=speaker, text=text))

    # Ada, then Bo mentions Cy; after Cy, Ada has waited longest.
    assert order == ["Ada", "Bo", "Cy", "Ada", "Bo"]


def test_the_user_can_mention_who_answers() -> None:
    room = room_with(FakeProvider([]))
    room.info.lines.append(Line(speaker="Ada", text="Hi"))
    room.say("What does @cy think?")

    assert room.next_speaker().name == "Cy"


def test_an_agent_mentioning_itself_doesnt_get_the_floor_back() -> None:
    room = room_with(FakeProvider([]))
    room.info.lines.append(Line(speaker="Ada", text="As @Ada, I say tabs."))

    assert room.next_speaker().name == "Bo"


def test_a_run_strips_names_cuts_off_lines_for_others_and_adds_up_the_cost(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        [
            reply("Ada: Tabs, they let you pick a width."),
            reply("[Bo]: Spaces.\n[Cy]: I agree with Bo.\n[Ada]: no"),
            reply("Whatever the formatter does.", model="local/thing"),
        ]
    )
    room = room_with(provider, folder=tmp_path)

    events = collect(room, 3)

    lines = [e.line for e in events if isinstance(e, LineAdded)]
    assert [(line.speaker, line.text) for line in lines] == [
        ("Ada", "Tabs, they let you pick a width."),
        ("Bo", "Spaces."),
        ("Cy", "Whatever the formatter does."),
    ]
    assert events[-1] == RoomStopped(reason="turns")
    assert lines[2].dollars is None
    assert room.info.unpriced == ["local/thing"]
    assert room.info.dollars == pytest.approx(2 * (1000 * 0.10 + 1000 * 0.50) / 1e6)
    saved = load_room(tmp_path, room.id[:15])
    assert saved == room.info
    assert recent_rooms(tmp_path)[0].id == room.id


def test_streamed_text_holds_back_a_name_and_a_line_for_someone_else() -> None:
    provider = Chunked(["Bo", ": Spa", "ces, always.", "\n[A", "da]: tabs!"])
    room = room_with(provider)
    room.info.lines.append(Line(speaker="Ada", text="Tabs."))

    events = collect(room, 1)

    streamed = "".join(e.text for e in events if isinstance(e, SpeakerText))
    assert streamed == "Spaces, always."
    assert [e.line.text for e in events if isinstance(e, LineAdded)] == ["Spaces, always."]


def test_the_budget_stops_the_room_before_a_turn() -> None:
    provider = FakeProvider([reply("One.", tokens=1_000_000), reply("Two.")])
    room = room_with(provider, budget=0.10)

    events = collect(room, 5)

    assert [e.line.text for e in events if isinstance(e, LineAdded)] == ["One."]
    assert isinstance(events[-1], RoomStopped) and events[-1].reason == "budget"
    assert "$0.10 budget" in events[-1].detail


def test_a_model_that_fails_stops_the_room_and_says_who() -> None:
    room = room_with(FakeProvider([reply("Hi.")]))

    events = collect(room, 3)

    assert isinstance(events[-1], RoomStopped)
    assert events[-1].reason == "error"
    assert events[-1].detail.startswith("Bo (m2): ")


def test_stopping_mid_reply_keeps_what_was_said_as_cut_off(tmp_path: Path) -> None:
    provider = Chunked(["Tabs are ", "better because ", "never shown"], wait=0.05)
    room = room_with(provider, folder=tmp_path)

    async def go() -> None:
        async def run() -> None:
            async for _ in room.run(1):
                pass

        task = asyncio.create_task(run())
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())

    assert room.info.lines == [
        Line(speaker="Ada", text="Tabs are better because", model="m1", cut=True)
    ]
    assert load_room(tmp_path, room.id).lines[0].cut


def test_agent_names_must_be_distinct_and_not_the_users() -> None:
    with pytest.raises(RoomError, match="Two agents are called"):
        check_agents([AgentSpec(name="Ada", model="m"), AgentSpec(name="ada", model="m")])
    with pytest.raises(RoomError, match="name the room gives you"):
        check_agents([AgentSpec(name="user", model="m")])
    with pytest.raises(RoomError, match="can't be an agent's name"):
        check_agents([AgentSpec(name="Ada Lovelace", model="m")])
    with pytest.raises(RoomError, match="at least one"):
        check_agents([])


def test_an_agent_is_name_equals_model_and_the_model_may_hold_colons() -> None:
    assert parse_agent("bo=ollama/qwen3:8b") == AgentSpec(name="bo", model="ollama/qwen3:8b")
    with pytest.raises(RoomError):
        parse_agent("bo")


def test_a_model_that_cant_be_used_names_the_agent() -> None:
    def make(model: str) -> Any:
        if model == "m2":
            raise ValueError("no key")
        return FakeProvider([])

    with pytest.raises(RoomError, match="Bo can't use m2: no key"):
        Room(RoomInfo(id="x", topic="t", agents=ADA_BO_CY), make)


# -- the command


def _script(path: Path, *texts: str) -> Path:
    path.write_text(json.dumps([reply(t).model_dump(mode="json") for t in texts]), "utf-8")
    return path


def test_the_room_command_runs_lists_and_resumes(tmp_path: Path) -> None:
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    runner = CliRunner()
    first = _script(tmp_path / "a.json", "Tabs.", "Spaces.")
    started = runner.invoke(
        app,
        [
            "room",
            "Tabs or spaces?",
            "-a",
            "Ada=claude-haiku-5-5",
            "-a",
            "Bo=claude-haiku-5-5",
            "--persona",
            "bo=a contrarian",
            "--turns",
            "2",
            "--fake-script",
            str(first),
        ],
        env=env,
    )
    listing = runner.invoke(app, ["room", "--list"], env=env)
    room_id = listing.output.split()[0]
    second = _script(tmp_path / "b.json", "Still tabs.")
    resumed = runner.invoke(
        app, ["room", "--resume", room_id, "--turns", "1", "--fake-script", str(second)], env=env
    )

    assert started.exit_code == 0, started.output
    assert "Bo · claude-haiku-5-5: a contrarian" in started.output
    assert "Tabs." in started.output and "Spaces." in started.output
    assert "2 lines" in listing.output
    assert resumed.exit_code == 0, resumed.output
    assert "So far:" in resumed.output
    assert "Still tabs." in resumed.output
    assert len(load_room(tmp_path / "home" / "rooms", room_id).lines) == 3


def test_the_room_command_explains_what_it_needs(tmp_path: Path) -> None:
    env = {"ZWANS_HOME": str(tmp_path / "home")}
    no_agents = CliRunner().invoke(app, ["room", "Hi"], env=env)
    bad_persona = CliRunner().invoke(
        app, ["room", "Hi", "-a", "ada=m", "--persona", "bo=x"], env=env
    )

    assert no_agents.exit_code == 2
    assert "--agent name=model" in no_agents.output
    assert bad_persona.exit_code == 2
    assert "doesn't name one of the agents" in bad_persona.output


# -- the server


@pytest.fixture
def client(tmp_path: Path) -> Any:
    providers: list[Any] = []
    settings = ServerSettings(
        config=Config(home=tmp_path / "home"),
        env={},
        token=TOKEN,
        make_provider=lambda config, model: providers[0],
    )
    with TestClient(create_app(settings)) as c:
        c.providers = providers  # type: ignore[attr-defined]
        yield c


def _until_idle(ws: Any) -> list[dict[str, Any]]:
    """Messages until the room says it has stopped talking."""
    seen = []
    while True:
        message = ws.receive_json()
        seen.append(message)
        if message["type"] == "room" and not message["running"]:
            return seen


def test_a_room_in_the_server_talks_streams_and_takes_the_users_line(client: Any) -> None:
    client.providers.append(FakeProvider([reply("Tabs."), reply("Spaces."), reply("Fine, tabs.")]))
    body = {
        "topic": "Tabs or spaces?",
        "agents": [{"name": "Ada", "model": "m1"}, {"name": "Bo", "model": "m2"}],
        "turns": 0,
    }
    created = client.post("/api/rooms", json=body, headers=AUTH)
    room_id = created.json()["id"]

    with client.websocket_connect(f"/api/rooms/{room_id}/events") as ws:
        ws.send_json({"type": "auth", "token": TOKEN})
        first = ws.receive_json()
        ws.send_json({"type": "continue", "turns": 2})
        run = _until_idle(ws)
        ws.send_json({"type": "say", "text": "@Bo, concede.", "turns": 1})
        said = _until_idle(ws)

    listed = client.get("/api/rooms", headers=AUTH).json()["saved"]
    assert created.status_code == 201, created.text
    assert first["type"] == "room" and first["lines"] == [] and first["next"] == "Ada"
    kinds = [m["type"] for m in run]
    assert kinds.count("speaker_started") == 2 and kinds.count("line_added") == 2
    assert run[-2] == {"type": "room_stopped", "reason": "turns", "detail": ""}
    assert said[0]["line"]["speaker"] == USER
    assert [line["text"] for line in said[-1]["lines"]] == [
        "Tabs.",
        "Spaces.",
        "@Bo, concede.",
        "Fine, tabs.",
    ]
    assert said[-1]["lines"][-1]["speaker"] == "Bo"
    assert listed[0]["id"] == room_id and listed[0]["lines"] == 4


def test_a_room_can_be_stopped_closed_and_opened_again(client: Any) -> None:
    client.providers.append(Chunked(["Tabs are ", "better ", "because ", "reasons"], wait=0.2))
    body = {"topic": "Tabs?", "agents": [{"name": "Ada", "model": "m1"}], "turns": 1}
    room_id = client.post("/api/rooms", json=body, headers=AUTH).json()["id"]

    with client.websocket_connect(f"/api/rooms/{room_id}/events") as ws:
        ws.send_json({"type": "auth", "token": TOKEN})
        while ws.receive_json()["type"] != "speaker_text":
            pass
        ws.send_json({"type": "say", "text": "hi"})
        busy = ws.receive_json()
        while busy["type"] != "server_error":
            busy = ws.receive_json()
        ws.send_json({"type": "stop"})
        stopped = _until_idle(ws)

    closed = client.delete(f"/api/rooms/{room_id}", headers=AUTH)
    gone = client.get(f"/api/rooms/{room_id}", headers=AUTH)
    reopened = client.post(f"/api/rooms/{room_id[:15]}/open", headers=AUTH)

    assert "Wait for the agent" in busy["message"]
    assert {"type": "room_stopped", "reason": "stopped", "detail": ""} in stopped
    assert stopped[-1]["lines"][0]["cut"] is True
    assert closed.status_code == 204
    assert gone.status_code == 404
    assert reopened.status_code == 200 and reopened.json()["lines"][0]["cut"] is True


def test_a_room_with_a_bad_agent_is_refused(client: Any) -> None:
    body = {"topic": "Hi", "agents": [{"name": "User", "model": "m1"}]}
    response = client.post("/api/rooms", json=body, headers=AUTH)

    assert response.status_code == 400
    assert "name the room gives you" in response.json()["detail"]


def test_room_sockets_need_the_token(client: Any) -> None:
    from starlette.websockets import WebSocketDisconnect

    with client.websocket_connect("/api/rooms/nope/events") as ws:
        ws.send_json({"type": "auth", "token": "wrong"})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4401
