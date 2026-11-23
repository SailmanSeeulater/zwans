import asyncio
import base64
import json
import os
import shutil
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zwans import pricing
from zwans.config import Config
from zwans.eval.runner import AttemptResult, EvalConfig, Report, Summary
from zwans.executor.seatbelt import SANDBOX_EXEC
from zwans.messages import ImageBlock, Message, TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse, StreamItem
from zwans.providers.fake import FakeProvider
from zwans.providers.router import ModelRouter
from zwans.server.app import ServerSettings, create_app
from zwans.tools.base import Tool

TOKEN = "test-token"
SANDBOXED = sys.platform == "darwin" and os.access(SANDBOX_EXEC, os.X_OK)
CHAT_TOOLS = ["WebFetch", "Python"] if SANDBOXED else ["WebFetch"]
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class SlowProvider(FakeProvider):
    """Waits before each response, so a test can act while a turn is running."""

    def __init__(self, script: Sequence[ModelResponse], delay: float) -> None:
        super().__init__(script)
        self.delay = delay

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        await asyncio.sleep(self.delay)
        async for item in super().stream(system, messages, tools):
            yield item


def say(text: str) -> ModelResponse:
    return ModelResponse(content=[TextBlock(text=text)], stop_reason="end_turn")


def write(path: str, content: str) -> ModelResponse:
    call = ToolUseBlock(id="w1", name="Write", input={"path": path, "content": content})
    return ModelResponse(content=[call], stop_reason="tool_use")


class Server:
    def __init__(self, tmp_path: Path) -> None:
        self.workspace = tmp_path / "ws"
        self.workspace.mkdir()
        self.reports = tmp_path / "reports"
        self.scripts: list[FakeProvider] = []  # one per session, in the order they open
        settings = ServerSettings(
            config=Config(home=tmp_path / "home", subagents=False),
            env={},
            token=TOKEN,
            reports=self.reports,
            make_provider=lambda config, model: self.scripts.pop(0),
        )
        self.client = TestClient(create_app(settings))

    def new_session(self, provider: FakeProvider, mode: str = "auto") -> str:
        self.scripts.append(provider)
        body = {"workspace": str(self.workspace), "mode": mode}
        response = self.client.post("/api/sessions", json=body, headers=AUTH)
        assert response.status_code == 201, response.text
        session_id: str = response.json()["id"]
        return session_id


@pytest.fixture
def server(tmp_path: Path) -> Iterator[Server]:
    s = Server(tmp_path)
    with s.client:
        yield s


def connect(server: Server, session_id: str) -> Any:
    ws = server.client.websocket_connect(f"/api/sessions/{session_id}/events")
    return ws


def handshake(ws: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ws.send_json({"type": "auth", "token": TOKEN})
    status = ws.receive_json()
    backlog = ws.receive_json()
    assert (status["type"], backlog["type"]) == ("status", "backlog")
    return status, backlog["events"]


def until(ws: Any, kind: str) -> list[dict[str, Any]]:
    """Messages up to and including the first of type `kind`."""
    seen = []
    while True:
        message = ws.receive_json()
        seen.append(message)
        if message["type"] == kind:
            return seen


def types(messages: list[dict[str, Any]]) -> list[str]:
    return [m["type"] for m in messages if m["type"] not in ("status", "text_delta")]


def test_everything_but_health_needs_the_token(server: Server) -> None:
    assert server.client.get("/api/health").json()["ok"] is True
    assert server.client.get("/api/sessions").status_code == 401
    wrong = {"Authorization": "Bearer nope"}
    assert server.client.get("/api/sessions", headers=wrong).status_code == 401
    assert server.client.get("/api/sessions", headers=AUTH).status_code == 200


def test_a_session_runs_a_turn_over_the_websocket(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("Hello from Zwans.")]))

    with connect(server, session_id) as ws:
        status, backlog = handshake(ws)
        assert status["running"] is False and backlog == []
        ws.send_json({"type": "prompt", "text": "Say hello."})
        messages = until(ws, "turn_ended")
        idle = ws.receive_json()

    assert types(messages) == ["turn_started", "usage_updated", "model_call", "turn_ended"]
    text = "".join(m["text"] for m in messages if m["type"] == "text_delta")
    assert text == "Hello from Zwans."
    assert messages[0]["type"] == "status" and messages[0]["running"] is True
    assert idle["type"] == "status" and idle["running"] is False and idle["turns"] == 1
    assert idle["title"] == "Say hello."


def test_a_chat_has_no_folder_or_file_tools_and_is_still_one_when_resumed(
    server: Server, tmp_path: Path
) -> None:
    first, second = FakeProvider([say("Hi.")]), FakeProvider([say("Still here.")])
    server.scripts += [first, second]
    body = {"chat": True, "model": "claude-haiku-5-5"}  # the home screen's pick, not the config's
    created = server.client.post("/api/sessions", json=body, headers=AUTH)
    assert created.status_code == 201, created.text
    status = created.json()
    url = f"/api/sessions/{status['id']}"
    folder = Path(status["workspace"])
    assert (status["chat"], status["model"]) == (True, "claude-haiku-5-5")
    assert folder.parent == (tmp_path / "home" / "chats").resolve()
    assert list(folder.iterdir()) == []

    with connect(server, status["id"]) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Hello."})
        until(ws, "turn_ended")
    assert first.last_request is not None
    # Nothing for the user's files or commands: the web, and Python where a sandbox can
    # hold it, which is on a Mac.
    assert [tool["name"] for tool in first.last_request["tools"]] == CHAT_TOOLS
    assert "no project open" in first.last_request["system"][0]["text"]
    [saved] = server.client.get("/api/sessions", headers=AUTH).json()["saved"]
    assert saved["chat"] is True
    undo = server.client.post(f"{url}/rewind", json={"turn": 1}, headers=AUTH)
    assert undo.status_code == 400 and "no files to put back" in undo.json()["detail"]

    # Closed and resumed, even with its folder gone: there was never anything in it.
    assert server.client.delete(url, headers=AUTH).status_code == 204
    shutil.rmtree(folder)
    reopened = server.client.post(f"{url}/open", headers=AUTH).json()
    assert reopened["chat"] is True and folder.is_dir()
    with connect(server, status["id"]) as ws:
        _, backlog = handshake(ws)
        assert "turn_ended" in types(backlog)
        ws.send_json({"type": "prompt", "text": "Are you there?"})
        until(ws, "turn_ended")
    assert second.last_request is not None
    assert [tool["name"] for tool in second.last_request["tools"]] == CHAT_TOOLS


def test_a_chat_nobody_spoke_in_leaves_nothing_behind(server: Server) -> None:
    server.scripts.append(FakeProvider([]))
    status = server.client.post("/api/sessions", json={"chat": True}, headers=AUTH).json()
    assert Path(status["workspace"]).is_dir()

    server.client.delete(f"/api/sessions/{status['id']}", headers=AUTH)

    assert not Path(status["workspace"]).exists()
    assert server.client.get("/api/sessions", headers=AUTH).json()["saved"] == []


def test_a_session_in_a_folder_is_not_a_chat(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("Hi.")]))
    status = server.client.get(f"/api/sessions/{session_id}", headers=AUTH).json()
    assert status["chat"] is False

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Hello."})
        until(ws, "turn_ended")
    [saved] = server.client.get("/api/sessions", headers=AUTH).json()["saved"]
    assert saved["chat"] is False


def test_the_models_question_is_answered_over_the_websocket(server: Server) -> None:
    asks = ModelResponse(
        content=[
            ToolUseBlock(
                id="q1",
                name="AskUser",
                input={"question": "Tabs or spaces?", "options": ["Spaces", "Tabs"]},
            )
        ],
        stop_reason="tool_use",
    )
    session_id = server.new_session(FakeProvider([asks, say("Spaces it is.")]))

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "answer", "text": "Too early"})  # nothing has been asked yet
        early = ws.receive_json()
        ws.send_json({"type": "prompt", "text": "Format the file."})
        asked = until(ws, "tool_call_requested")[-1]
        while True:  # the status that says the question is waiting
            message = ws.receive_json()
            if message["type"] == "status" and message["waiting_for"] == ["question"]:
                break
        ws.send_json({"type": "answer", "text": " Tabs "})
        answered = until(ws, "tool_result")[-1]
        until(ws, "turn_ended")
        idle = ws.receive_json()

    assert early == {"type": "server_error", "message": "No question is waiting for an answer."}
    assert asked["args"]["options"] == ["Spaces", "Tabs"]
    assert answered["content"] == "The user answered: Tabs"
    assert idle["waiting_for"] == []


def test_approvals_go_back_over_the_websocket(server: Server) -> None:
    session_id = server.new_session(
        FakeProvider([write("yes.txt", "1"), write("no.txt", "2"), say("Done.")]), mode="ask"
    )

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Write two files."})
        asked = until(ws, "permission_requested")[-1]
        ws.send_json({"type": "approve", "call_id": asked["call_id"], "answer": "once"})
        until(ws, "tool_result")
        asked = until(ws, "permission_requested")[-1]
        ws.send_json({"type": "approve", "call_id": asked["call_id"], "answer": "no"})
        refused = until(ws, "tool_result")[-1]
        until(ws, "turn_ended")

    assert (server.workspace / "yes.txt").read_text() == "1"
    assert not (server.workspace / "no.txt").exists()
    assert refused["is_error"] is True


def test_a_prompt_sent_mid_turn_steers_it(server: Server) -> None:
    provider = FakeProvider([write("a.txt", "1"), say("Done, with tabs.")])
    session_id = server.new_session(provider, mode="ask")

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Write a."})
        asked = until(ws, "permission_requested")[-1]
        ws.send_json({"type": "prompt", "text": "Use tabs."})
        queued = until(ws, "status")[-1]
        while not queued.get("queued"):  # a status sent before the steer may come first
            queued = until(ws, "status")[-1]
        ws.send_json({"type": "approve", "call_id": asked["call_id"], "answer": "once"})
        steered = until(ws, "steered")[-1]
        until(ws, "turn_ended")

    assert queued["running"] is True and queued["queued"] == ["Use tabs."]
    assert steered["text"] == "Use tabs."
    sent = provider.requests[1][-1].content
    assert any(isinstance(b, TextBlock) and b.text.endswith("Use tabs.") for b in sent)


def test_a_second_client_gets_the_backlog_and_follows_along(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("First."), say("Second.")]))

    with connect(server, session_id) as first:
        handshake(first)
        first.send_json({"type": "prompt", "text": "One."})
        until(first, "turn_ended")
        with connect(server, session_id) as second:
            _, backlog = handshake(second)
            assert types(backlog) == ["turn_started", "usage_updated", "model_call", "turn_ended"]
            second.send_json({"type": "prompt", "text": "Two."})
            seen_by_first = until(first, "turn_ended")
            seen_by_second = until(second, "turn_ended")

    assert types(seen_by_first) == types(seen_by_second)
    prompts = [m["prompt"] for m in seen_by_first if m["type"] == "turn_started"]
    assert prompts == ["Two."]


def test_a_stopped_turn_hands_what_was_sent_during_it_to_the_next(server: Server) -> None:
    provider = SlowProvider([say("Too slow."), say("On it.")], delay=5)
    session_id = server.new_session(provider)
    image = {"name": "shot.png", "data": base64.b64encode(PNG).decode()}

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Take your time."})
        until(ws, "turn_started")
        ws.send_json({"type": "prompt", "text": "Look", "images": [image]})
        refused = until(ws, "server_error")[-1]
        ws.send_json({"type": "prompt", "text": "And another."})
        provider.delay = 0
        ws.send_json({"type": "interrupt"})
        ended = until(ws, "turn_ended")[-1]
        started = until(ws, "turn_started")[-1]
        until(ws, "turn_ended")

    assert "can't be added to a running turn" in refused["message"]
    assert ended["stop_reason"] == "interrupted"
    assert started["prompt"] == "And another."


def test_websockets_need_the_token_an_open_session_and_this_origin(server: Server) -> None:
    session_id = server.new_session(FakeProvider([]))

    with connect(server, session_id) as ws:
        ws.send_json({"type": "auth", "token": "wrong"})
        with pytest.raises(WebSocketDisconnect) as refused:
            ws.receive_json()
    assert refused.value.code == 4401

    with connect(server, "20990101-000000-none") as ws:
        ws.send_json({"type": "auth", "token": TOKEN})
        with pytest.raises(WebSocketDisconnect) as missing:
            ws.receive_json()
    assert missing.value.code == 4404

    evil = server.client.websocket_connect(
        f"/api/sessions/{session_id}/events", headers={"origin": "https://evil.example"}
    )
    with pytest.raises(WebSocketDisconnect), evil:
        pass


def test_a_saved_session_reopens_with_its_history(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("Before.")]))
    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Earlier."})
        until(ws, "turn_ended")
    assert server.client.delete(f"/api/sessions/{session_id}", headers=AUTH).status_code == 204
    listed = server.client.get("/api/sessions", headers=AUTH).json()
    assert listed["live"] == []
    assert [s["id"] for s in listed["saved"]] == [session_id]

    server.scripts.append(FakeProvider([say("After.")]))
    reopened = server.client.post(f"/api/sessions/{session_id[:15]}/open", headers=AUTH)

    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["turns"] == 1
    with connect(server, session_id) as ws:
        _, backlog = handshake(ws)
    assert [e["prompt"] for e in backlog if e["type"] == "turn_started"] == ["Earlier."]
    missing = server.client.post("/api/sessions/nope/open", headers=AUTH)
    assert missing.status_code == 404


# A 2x3 PNG's signature and IHDR chunk: enough to be recognized as an image.
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x03" + b"\x00" * 16


def test_a_prompt_can_carry_images(server: Server) -> None:
    provider = FakeProvider([say("A tiny image."), say("Just text.")])
    session_id = server.new_session(provider)
    image = {"name": "shot.png", "data": base64.b64encode(PNG).decode()}

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "What is this?", "images": [image]})
        started = until(ws, "turn_ended")
        ws.send_json({"type": "prompt", "text": "", "images": [{"name": "a.txt", "data": "aGk="}]})
        refused = until(ws, "server_error")
        ws.send_json({"type": "prompt", "text": "Hi", "images": [{"data": "not base64!"}]})
        garbled = until(ws, "server_error")

    turn = next(m for m in started if m["type"] == "turn_started")
    assert turn["images"] == 1 and turn["turn"] == 1 and turn["prompt"] == "What is this?"
    sent = provider.requests[0][-1].content
    assert isinstance(sent[0], ImageBlock) and sent[0].source.media_type == "image/png"
    assert "a.txt isn't a PNG, JPEG, GIF or WebP image." in refused[-1]["message"]
    assert "image 1 isn't base64." in garbled[-1]["message"]


def _run(server: Server, session_id: str, *prompts: str) -> None:
    with connect(server, session_id) as ws:
        handshake(ws)
        for prompt in prompts:
            ws.send_json({"type": "prompt", "text": prompt})
            until(ws, "turn_ended")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_undoing_a_turn_puts_the_files_back_and_drops_it(server: Server) -> None:
    script = [write("a.txt", "1"), say("Wrote a."), write("b.txt", "2"), say("Wrote b.")]
    session_id = server.new_session(FakeProvider(script))
    _run(server, session_id, "Write a", "Write b")
    base = f"/api/sessions/{session_id}"

    listed = server.client.get(f"{base}/turns", headers=AUTH).json()
    server.scripts.append(FakeProvider([]))  # for the reopened session
    undone = server.client.post(f"{base}/rewind", json={"turn": 2}, headers=AUTH)
    with connect(server, session_id) as ws:
        _, backlog = handshake(ws)

    assert listed["problem"] is None
    assert [(t["turn"], t["prompt"], t["changes"]) for t in listed["turns"]] == [
        (2, "Write b", [{"status": "added", "path": "b.txt"}]),
        (1, "Write a", [{"status": "added", "path": "a.txt"}]),
    ]
    assert undone.status_code == 200, undone.text
    body = undone.json()
    assert body["draft"] == "Write b" and body["status"]["turns"] == 1
    assert body["undone"] == [{"status": "deleted", "path": "b.txt"}]
    assert (server.workspace / "a.txt").exists() and not (server.workspace / "b.txt").exists()
    assert [e["prompt"] for e in backlog if e["type"] == "turn_started"] == ["Write a"]

    server.scripts.append(FakeProvider([]))
    again = server.client.post(f"{base}/rewind", json={"turn": 1}, headers=AUTH)
    with connect(server, session_id) as ws:
        _, backlog = handshake(ws)
    assert again.status_code == 200, again.text
    assert not (server.workspace / "a.txt").exists() and backlog == []
    missing = server.client.post(f"{base}/rewind", json={"turn": 5}, headers=AUTH)
    assert missing.status_code == 400
    assert "no checkpoint from before turn 5" in missing.json()["detail"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_changes_panel_gets_everything_the_session_changed(server: Server) -> None:
    (server.workspace / "keep.txt").write_text("old\n")
    script = [write("keep.txt", "new\n"), say("Changed."), write("b.txt", "2"), say("Wrote b.")]
    session_id = server.new_session(FakeProvider(script))
    _run(server, session_id, "Change keep", "Write b")

    body = server.client.get(f"/api/sessions/{session_id}/changes", headers=AUTH).json()

    assert body["problem"] is None and body["cut"] is False
    assert sorted((c["status"], c["path"]) for c in body["changes"]) == [
        ("added", "b.txt"),
        ("changed", "keep.txt"),
    ]
    assert "-old" in body["diff"] and "+new" in body["diff"] and "+++ b/b.txt" in body["diff"]


def test_only_a_local_session_offers_to_hand_off(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = server.new_session(FakeProvider([]))
    status = server.client.get("/api/sessions", headers=AUTH).json()["live"]
    hosted = next(s for s in status if s["id"] == session_id)
    # As if its provider were one on this machine, such as Ollama.
    monkeypatch.setattr(pricing, "FREE_PROVIDERS", {hosted["model"].partition("/")[0]})
    with connect(server, session_id) as ws:
        local, _ = handshake(ws)

    assert hosted["local"] is False and hosted["handoff_model"] is None
    assert local["local"] is True and local["handoff_model"] == "claude-sonnet-5-5"


def _finished(server: Server, session_id: str) -> None:
    with connect(server, session_id) as ws:
        _, backlog = handshake(ws)
        if not any(e["type"] == "turn_ended" for e in backlog):
            until(ws, "turn_ended")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_race_runs_two_models_in_copies_and_keeps_the_chosen_result(server: Server) -> None:
    (server.workspace / "a.txt").write_text("old\n")
    server.scripts += [
        FakeProvider([write("a.txt", "from a\n"), say("A done.")]),
        FakeProvider([write("a.txt", "from b\n"), say("B done.")]),
    ]
    body = {
        "workspace": str(server.workspace),
        "prompt": "Change a",
        "models": ["claude-opus-5-5", "claude-sonnet-5-5"],
        "mode": "auto",
    }

    started = server.client.post("/api/races", json=body, headers=AUTH)
    assert started.status_code == 201, started.text
    race = started.json()
    for lane in race["lanes"]:
        _finished(server, lane["session_id"])
    a, b = race["lanes"]
    kept = server.client.post(
        f"/api/races/{race['id']}/keep", json={"session_id": b["session_id"]}, headers=AUTH
    )
    again = server.client.get(f"/api/races/{race['id']}", headers=AUTH).json()

    assert [lane["model"] for lane in race["lanes"]] == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert Path(a["folder"], "a.txt").read_text() == "from a\n"
    assert kept.status_code == 200, kept.text
    assert kept.json()["kept"] == [{"status": "changed", "path": "a.txt"}]
    assert (server.workspace / "a.txt").read_text() == "from b\n"
    assert again["kept"] == b["session_id"]
    one_model = {**body, "models": ["claude-opus-5-5"]}
    refused = server.client.post("/api/races", json=one_model, headers=AUTH)
    assert refused.status_code == 400 and "takes 2 models" in refused.json()["detail"]


def _ended(server: Server, session_id: str) -> dict[str, Any]:
    with connect(server, session_id) as ws:
        _, backlog = handshake(ws)
        ended = [e for e in backlog if e["type"] == "turn_ended"]
        return ended[-1] if ended else until(ws, "turn_ended")[-1]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_race_budget_is_shared_by_both_models(server: Server) -> None:
    def costly(name: str) -> ModelResponse:
        reply = write(f"{name}.txt", name)
        return reply.model_copy(update={"model": "claude-opus-5-5", "output_tokens": 100_000})

    server.scripts += [
        FakeProvider([costly("a"), say("A done.")]),
        FakeProvider([costly("b"), say("B done.")]),
    ]
    body = {
        "workspace": str(server.workspace),
        "prompt": "Write a file",
        "models": ["claude-opus-5-5", "claude-sonnet-5-5"],
        "mode": "auto",
        "budget": 0.5,
    }

    race = server.client.post("/api/races", json=body, headers=AUTH).json()
    ended = [_ended(server, lane["session_id"]) for lane in race["lanes"]]
    status = server.client.get(f"/api/races/{race['id']}", headers=AUTH).json()
    listed = server.client.get("/api/races", headers=AUTH).json()["races"]
    free = {**body, "budget": 0}
    refused = server.client.post("/api/races", json=free, headers=AUTH)

    assert race["budget"] == 0.5
    assert [e["stop_reason"] for e in ended] == ["budget", "budget"]
    assert "race's $0.50 budget" in ended[0]["detail"]
    assert status["dollars"] >= 0.5
    assert status["dollars"] == sum(lane["dollars"] for lane in status["lanes"])
    assert all(lane["live"] and not lane["running"] for lane in status["lanes"])
    assert [r["id"] for r in listed] == [race["id"]]
    assert refused.status_code == 400 and "more than $0" in refused.json()["detail"]


def test_a_loop_runs_over_the_websocket_and_a_budget_stops_it(server: Server) -> None:
    priced = ModelResponse(
        content=[TextBlock(text="Tried.")],
        stop_reason="end_turn",
        output_tokens=100_000,
        model="claude-opus-5-5",
    )
    session_id = server.new_session(FakeProvider([priced, say("Not sent.")]))

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "budget", "dollars": "$0.01"})
        capped = until(ws, "status")[-1]
        ws.send_json({"type": "loop", "argument": "3 until exit 1"})
        seen = until(ws, "loop_ended")
        ws.send_json({"type": "loop", "argument": "pytest"})
        refused = until(ws, "server_error")[-1]

    assert capped["budget"] == 0.01
    checks = [m for m in seen if m["type"] == "loop_checked"]
    assert [(c["round"], c["passed"]) for c in checks] == [(0, False), (1, False)]
    ended = [m for m in seen if m["type"] == "turn_ended"]
    assert ended[-1]["stop_reason"] == "budget"
    assert seen[-1]["reason"] == "budget"
    assert "Usage: /loop" in refused["message"]


def test_a_session_downloads_as_a_replay_page(server: Server) -> None:
    session_id = server.new_session(FakeProvider([write("a.txt", "1"), say("Wrote a.")]))
    _run(server, session_id, "Write a")

    page = server.client.get(f"/api/sessions/{session_id}/replay", headers=AUTH)
    missing = server.client.get("/api/sessions/nope/replay", headers=AUTH)

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert f'filename="zwans-replay-{session_id}.html"' in page.headers["content-disposition"]
    assert '"prompt": "Write a"' in page.text and '"text": "Wrote a."' in page.text
    assert missing.status_code == 404


def test_commands_from_files_run_over_the_websocket(server: Server) -> None:
    folder = server.workspace / ".zwans" / "commands"
    folder.mkdir(parents=True)
    (folder / "review.md").write_text("---\ndescription: Review a file\n---\nReview $1.")
    (folder / "finish.md").write_text(
        "---\nloop: test -f done.txt || (echo missing; exit 1)\nrounds: 2\n---\nFinish."
    )
    script = [say("Reviewed."), write("done.txt", "ok"), say("Done.")]
    session_id = server.new_session(FakeProvider(script))

    with connect(server, session_id) as ws:
        status, _ = handshake(ws)
        ws.send_json({"type": "command", "name": "review", "argument": "app.py"})
        reviewed = until(ws, "turn_ended")
        ws.send_json({"type": "command", "name": "finish", "argument": ""})
        asked = until(ws, "command_needs_trust")[-1]
        ws.send_json({"type": "command", "name": "finish", "argument": "", "trust": True})
        looped = until(ws, "loop_ended")
        ws.send_json({"type": "command", "name": "nope", "argument": ""})
        missing = until(ws, "server_error")[-1]

    assert [c["name"] for c in status["commands"]] == ["finish", "review"]
    assert status["commands"][1]["description"] == "Review a file"
    started = next(m for m in reviewed if m["type"] == "turn_started")
    assert started["prompt"] == "Review app.py."
    assert asked["check"].startswith("test -f done.txt") and asked["path"].endswith("finish.md")
    assert looped[-1]["reason"] == "passed"
    assert missing["message"] == "There's no /nope."


def test_a_new_session_needs_a_real_folder(server: Server, tmp_path: Path) -> None:
    body = {"workspace": str(tmp_path / "missing")}
    response = server.client.post("/api/sessions", json=body, headers=AUTH)
    assert response.status_code == 400
    assert "isn't a folder" in response.json()["detail"]


def _report(model: str, passed: bool) -> Report:
    attempt = AttemptResult(
        task="buggy-calc",
        category="bug-fix",
        repeat=1,
        status="passed" if passed else "failed",
        stop_reason="end_turn",
        dollars=0.1,
        model_calls=4,
        tool_calls=3,
        transcript="evals/reports/run/transcripts/buggy-calc-1.jsonl",
    )
    return Report(
        config=EvalConfig(name="default"),
        model=model,
        effort="low",
        started_at=f"2026-10-30T10:00:0{int(passed)}",
        repeats=1,
        budget=None,
        out_of_budget=False,
        summary=Summary.of([attempt]),
        tasks={"buggy-calc": Summary.of([attempt])},
        attempts=[attempt],
    )


def test_eval_reports_transcripts_and_comparisons(server: Server) -> None:
    for name, passed in (("old", False), ("new", True)):
        folder = server.reports / name
        (folder / "transcripts").mkdir(parents=True)
        (folder / "report.json").write_text(_report("m", passed).model_dump_json())
        events = [{"type": "turn_started", "prompt": "Fix it."}, {"type": "turn_ended"}]
        lines = "\n".join(json.dumps(e) for e in events) + "\n"
        (folder / "transcripts" / "buggy-calc-1.jsonl").write_text(lines)
    (server.reports / "broken").mkdir()

    runs = server.client.get("/api/evals", headers=AUTH).json()
    run = server.client.get("/api/evals/new", headers=AUTH).json()
    transcript = server.client.get(
        "/api/evals/new/transcripts/buggy-calc-1.jsonl", headers=AUTH
    ).json()
    compared = server.client.get("/api/evals/compare?a=old&b=new", headers=AUTH).json()

    assert [r["name"] for r in runs] == ["old", "new"]  # oldest first; broken is skipped
    assert run["attempts"][0]["transcript"] == "buggy-calc-1.jsonl"
    assert [e["type"] for e in transcript] == ["turn_started", "turn_ended"]
    assert compared["task_pass_rates"] == {"buggy-calc": [0.0, 1.0]}
    assert compared["differences"][0]["metric"] == "pass rate"
    for bad in ("/api/evals/..%2Fhome", "/api/evals/new/transcripts/..%2Freport.json"):
        assert server.client.get(bad, headers=AUTH).status_code == 404


def _eval_run(
    tasks: dict[str, list[bool]], dollars: float, agent: str = "zwans", started: str = "1"
) -> Report:
    """A report with one attempt per pass or fail listed for each task."""
    attempts = [
        AttemptResult(
            task=task,
            category="bug-fix",
            repeat=repeat,
            status="passed" if passed else "failed",
            stop_reason="end_turn",
            dollars=dollars,
            model_calls=4,
            seconds=10.0,
        )
        for task, results in tasks.items()
        for repeat, passed in enumerate(results, 1)
    ]
    by_task = {task: Summary.of([a for a in attempts if a.task == task]) for task in tasks}
    return Report(
        agent=agent,
        config=EvalConfig(name="default"),
        model="m",
        effort="low",
        started_at=f"2026-10-30T10:00:0{started}",
        repeats=max(map(len, tasks.values())),
        budget=None,
        out_of_budget=False,
        summary=Summary.of(attempts),
        tasks=by_task,
        attempts=attempts,
    )


def test_the_leaderboard_pools_runs_of_the_same_tasks_and_ranks_them(server: Server) -> None:
    six = [f"task-{n}" for n in range(6)]
    reports = {
        # The same thing run twice is one row: 6 of 6, then 5 of 6.
        "zwans-1": _eval_run({t: [True] for t in six}, dollars=0.02, started="1"),
        "zwans-2": _eval_run({t: [t != "task-0"] for t in six}, dollars=0.04, started="2"),
        # Passes everything, for ten times the money.
        "codex": _eval_run({t: [True, True] for t in six}, dollars=0.30, agent="codex 0.171.0"),
        # Never passes, and costs more than the pooled zwans row.
        "broken": _eval_run({t: [False] for t in six}, dollars=0.05, agent="other"),
        # Other tasks, so a board of its own, with too few tasks to tell rows apart.
        "small-a": _eval_run({"solo": [True, True, True]}, dollars=0.01),
        "small-b": _eval_run({"solo": [False]}, dollars=0.01, agent="other"),
    }
    for name, report in reports.items():
        (server.reports / name).mkdir(parents=True)
        (server.reports / name / "report.json").write_text(report.model_dump_json())

    big, small = server.client.get("/api/evals/leaderboard", headers=AUTH).json()

    assert (big["tasks"], big["runs"]) == (six, 4)  # the board with the most runs is first
    codex, zwans, broken = big["rows"]
    assert (codex["agent"], codex["standing"]) == ("codex 0.171.0", "best")
    assert (zwans["runs"], zwans["attempts"], zwans["passed"]) == (["zwans-1", "zwans-2"], 12, 11)
    assert zwans["mean_dollars"] == pytest.approx(0.03)
    assert zwans["standing"] == "level"  # one failure in twelve isn't clearly behind
    assert (broken["pass_rate"], broken["standing"]) == (0.0, "behind")
    # Cheaper or better than every other row puts a row on the frontier.
    assert [row["frontier"] for row in big["rows"]] == [True, True, False]
    # Three of three and none of six both leave room for doubt.
    assert codex["low"] < 0.8 and codex["high"] == 1.0
    assert broken["low"] == 0.0 and 0.3 < broken["high"] < 0.5

    assert small["tasks"] == ["solo"]
    assert [row["standing"] for row in small["rows"]] == ["best", "too_few_tasks"]
    assert small["rows"][0]["low"] == pytest.approx(0.438, abs=0.005)  # Wilson, 3 of 3


def test_without_a_built_ui_the_root_says_how_to_build_it(server: Server) -> None:
    assert "npm run build" in server.client.get("/").text


def test_the_last_request_is_shown_as_the_api_got_it(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("Hi.")]))
    url = f"/api/sessions/{session_id}/request"
    assert server.client.get(url, headers=AUTH).json() == {"request": None}

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Say hi."})
        until(ws, "turn_ended")

    request = server.client.get(url, headers=AUTH).json()["request"]
    said = {"role": "user", "content": [{"type": "text", "text": "Say hi."}]}
    assert request["messages"][-1] == said
    assert request["system"][0]["type"] == "text"
    assert {tool["name"] for tool in request["tools"]} >= {"Read", "Bash"}


def test_the_demo_info_says_why_the_model_cant_be_used_yet(tmp_path: Path) -> None:
    def info(model: str, env: dict[str, str]) -> dict[str, Any]:
        config = Config(home=tmp_path / "home", model=model)
        with TestClient(create_app(ServerSettings(config=config, env=env, token=TOKEN))) as client:
            found: dict[str, Any] = client.get("/api/demo", headers=AUTH).json()
            return found

    missing = info("claude-haiku-5-5", {})
    assert missing["has_credential"] is False
    assert "ANTHROPIC_API_KEY is not set" in missing["credential_problem"]
    assert missing["model"] == "claude-haiku-5-5"  # what the home screen's picker starts on

    with_key = info("claude-haiku-5-5", {"ANTHROPIC_API_KEY": "test-key"})
    assert (with_key["has_credential"], with_key["credential_problem"]) == (True, None)
    # A model on this machine needs no key at all.
    assert info("ollama/qwen3-coder", {})["credential_problem"] is None


def test_the_demo_fixes_its_project_and_compacts_on_the_second_turn(tmp_path: Path) -> None:
    settings = ServerSettings(
        config=Config(home=tmp_path / "home", subagents=False),
        env={},  # no credential: the demo never needs one
        token=TOKEN,
        demo_pace=0,
    )
    with TestClient(create_app(settings)) as client:
        prompts = client.get("/api/demo", headers=AUTH).json()["prompts"]
        response = client.post("/api/sessions", json={"demo": True, "mode": "auto"}, headers=AUTH)
        assert response.status_code == 201, response.text
        status = response.json()
        assert status["demo"] is True and status["compact_at"] < 10_000
        workspace = Path(status["workspace"])

        server = type("S", (), {"client": client})()
        with connect(server, status["id"]) as ws:
            handshake(ws)
            ws.send_json({"type": "prompt", "text": prompts[0]})
            first = until(ws, "turn_ended")
            ws.send_json({"type": "prompt", "text": prompts[1]})
            second = until(ws, "turn_ended")

    results = [m for m in first + second if m["type"] == "tool_result"]
    assert not any(m["is_error"] for m in results), results
    todos = [m for m in results if m["content"].startswith("To-do list saved")]
    assert len(todos) == 3  # the plan, kept up to date in the first turn
    results = [m for m in results if m not in todos]
    assert "FAILED (failures=1)" in results[0]["content"]
    assert "Ran 7 tests" in results[-1]["content"] and "\nOK\n" in results[-1]["content"]
    assert "_term(tokens)" in (workspace / "calc.py").read_text()
    assert "compaction" not in types(first) and types(second)[1] == "context_compacted"
    calls = [m for m in first + second if m["type"] == "model_call"]
    assert [c["purpose"] for c in calls].count("summary") == 1
    assert all(c["dollars"] for c in calls)


# -- switching models, and deleting a session


def test_a_session_on_claude_switches_to_a_local_model(server: Server, tmp_path: Path) -> None:
    # The route once ran in a worker thread, where saving the choice failed: the session's
    # SQLite connection only works on the thread that opened it.
    env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
    router = ModelRouter(Config(home=tmp_path / "home"), env, "claude-haiku-5-5")
    session_id = server.new_session(router)  # type: ignore[arg-type]
    url = f"/api/sessions/{session_id}"

    switched = server.client.post(f"{url}/model", json={"name": "ollama/qwen3:8b"}, headers=AUTH)
    back = server.client.post(f"{url}/model", json={"name": "claude-opus-5-5"}, headers=AUTH)
    unknown = server.client.post(f"{url}/model", json={"name": "nowhere/model"}, headers=AUTH)

    assert (switched.status_code, switched.json()["model"]) == (200, "ollama/qwen3:8b")
    assert (back.status_code, back.json()["model"]) == (200, "claude-opus-5-5")
    assert unknown.status_code == 400
    assert server.client.get(url, headers=AUTH).json()["model"] == "claude-opus-5-5"


def _said_hello(server: Server) -> str:
    """A session with one turn in it, so it's saved."""
    said = ModelResponse(content=[TextBlock(text="Hi.")], stop_reason="end_turn")
    session_id = server.new_session(FakeProvider([said]))
    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Hello."})
        until(ws, "turn_ended")
    return session_id


def test_deleting_a_session_removes_it_and_what_was_kept_for_it(
    server: Server, tmp_path: Path
) -> None:
    kept, gone = _said_hello(server), _said_hello(server)
    transcript = tmp_path / "home" / "transcripts" / f"{gone}.jsonl"
    assert transcript.exists()

    # Open or closed, it goes: one is deleted while open, then the other after closing.
    assert server.client.delete(f"/api/sessions/{gone}/saved", headers=AUTH).status_code == 204

    sessions = server.client.get("/api/sessions", headers=AUTH).json()
    assert [s["id"] for s in sessions["saved"]] == [kept]
    assert [s["id"] for s in sessions["live"]] == [kept]
    assert not transcript.exists()
    assert server.client.post(f"/api/sessions/{gone}/open", headers=AUTH).status_code == 404

    server.client.delete(f"/api/sessions/{kept}", headers=AUTH)  # closed, still saved
    assert server.client.delete(f"/api/sessions/{kept}/saved", headers=AUTH).status_code == 204
    assert server.client.get("/api/sessions", headers=AUTH).json()["saved"] == []


def test_deleting_refuses_a_session_that_isnt_there_or_only_starts_alike(server: Server) -> None:
    session_id = _said_hello(server)
    server.client.delete(f"/api/sessions/{session_id}", headers=AUTH)

    missing = server.client.delete("/api/sessions/20200101-0000-0000/saved", headers=AUTH)
    prefix = server.client.delete(f"/api/sessions/{session_id[:6]}/saved", headers=AUTH)

    assert missing.status_code == 404
    assert prefix.status_code == 404  # the start of an id resumes a session; it never deletes one
    assert len(server.client.get("/api/sessions", headers=AUTH).json()["saved"]) == 1


def test_a_session_is_renamed_and_pinned_open_or_not(server: Server) -> None:
    first, second = _said_hello(server), _said_hello(server)
    url = f"/api/sessions/{first}"

    with connect(server, first) as ws:
        handshake(ws)
        renamed = server.client.patch(f"{url}/saved", json={"name": " Say\nhello "}, headers=AUTH)
        assert renamed.status_code == 204
        assert until(ws, "status")[-1]["title"] == "Say hello"  # its page hears the new name
    pinned = server.client.patch(f"{url}/saved", json={"pinned": True}, headers=AUTH)
    assert pinned.status_code == 204

    saved = server.client.get("/api/sessions", headers=AUTH).json()["saved"]
    # The pinned one comes first, though the other was used last.
    assert [(s["id"], s["title"], s["named"], s["pinned"]) for s in saved] == [
        (first, "Say hello", True, True),
        (second, "Hello.", False, False),
    ]

    server.client.delete(url, headers=AUTH)  # closed, and its name taken off
    server.client.patch(f"{url}/saved", json={"name": ""}, headers=AUTH)
    top = server.client.get("/api/sessions", headers=AUTH).json()["saved"][0]
    assert (top["title"], top["named"], top["pinned"]) == ("Hello.", False, True)


def test_renaming_refuses_a_session_that_isnt_there_or_only_starts_alike(server: Server) -> None:
    session_id = _said_hello(server)
    body = {"name": "x"}
    missing = server.client.patch("/api/sessions/20200101-0000-0000/saved", json=body, headers=AUTH)
    prefix = server.client.patch(f"/api/sessions/{session_id[:6]}/saved", json=body, headers=AUTH)
    assert (missing.status_code, prefix.status_code) == (404, 404)


def test_after_its_first_turn_a_session_gets_a_title_from_haiku(
    server: Server, tmp_path: Path
) -> None:
    said = ModelResponse(content=[TextBlock(text="Hi.")], stop_reason="end_turn")
    named = ModelResponse(
        content=[TextBlock(text='"Saying hello."')], stop_reason="end_turn", input_tokens=30
    )
    backends = [FakeProvider([said]), FakeProvider([named])]  # the session's, then the title's
    asked: list[str] = []

    def make_backend(resolved: Any) -> FakeProvider:
        asked.append(resolved.name)
        return backends.pop(0)

    env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
    config = Config(home=tmp_path / "home")
    router = ModelRouter(config, env, "claude-opus-5-5", make_backend)  # type: ignore[arg-type]
    session_id = server.new_session(router)  # type: ignore[arg-type]
    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Hello there, how are you doing today?"})
        until(ws, "turn_ended")
        seen: list[dict[str, Any]] = []
        while not any(m["type"] == "status" and m["title"] == "Saying hello" for m in seen):
            seen.append(ws.receive_json())

    assert asked == ["claude-opus-5-5", "claude-haiku-5-5"]
    usage = [m for m in seen if m["type"] == "usage_updated"]
    assert [(u["purpose"], u["input_tokens"]) for u in usage] == [("title", 30)]
    saved = server.client.get("/api/sessions", headers=AUTH).json()["saved"]
    assert [(s["title"], s["named"]) for s in saved] == [("Saying hello", False)]
