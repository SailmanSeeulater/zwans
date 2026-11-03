import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zwans.config import Config
from zwans.eval.runner import AttemptResult, EvalConfig, Report, Summary
from zwans.events import TextDelta, ThinkingDelta
from zwans.messages import Message, TextBlock, ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.server.app import ServerSettings, create_app
from zwans.tools.base import Tool

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class SlowProvider(FakeProvider):
    """Waits before each response, so a test can act while a turn is running."""

    def __init__(self, script: Sequence[ModelResponse], delay: float) -> None:
        super().__init__(script)
        self.delay = delay

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[TextDelta | ThinkingDelta | ModelResponse]:
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

    assert types(messages) == ["turn_started", "usage_updated", "turn_ended"]
    text = "".join(m["text"] for m in messages if m["type"] == "text_delta")
    assert text == "Hello from Zwans."
    assert messages[0]["type"] == "status" and messages[0]["running"] is True
    assert idle["type"] == "status" and idle["running"] is False and idle["turns"] == 1
    assert idle["title"] == "Say hello."


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


def test_a_second_client_gets_the_backlog_and_follows_along(server: Server) -> None:
    session_id = server.new_session(FakeProvider([say("First."), say("Second.")]))

    with connect(server, session_id) as first:
        handshake(first)
        first.send_json({"type": "prompt", "text": "One."})
        until(first, "turn_ended")
        with connect(server, session_id) as second:
            _, backlog = handshake(second)
            assert types(backlog) == ["turn_started", "usage_updated", "turn_ended"]
            second.send_json({"type": "prompt", "text": "Two."})
            seen_by_first = until(first, "turn_ended")
            seen_by_second = until(second, "turn_ended")

    assert types(seen_by_first) == types(seen_by_second)
    prompts = [m["prompt"] for m in seen_by_first if m["type"] == "turn_started"]
    assert prompts == ["Two."]


def test_a_busy_session_refuses_another_prompt_and_can_be_interrupted(server: Server) -> None:
    session_id = server.new_session(SlowProvider([say("Too slow.")], delay=5))

    with connect(server, session_id) as ws:
        handshake(ws)
        ws.send_json({"type": "prompt", "text": "Take your time."})
        until(ws, "turn_started")
        ws.send_json({"type": "prompt", "text": "And another."})
        refused = until(ws, "server_error")[-1]
        ws.send_json({"type": "interrupt"})
        ended = until(ws, "turn_ended")[-1]

    assert "already running" in refused["message"]
    assert ended["stop_reason"] == "interrupted"


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


def test_without_a_built_ui_the_root_says_how_to_build_it(server: Server) -> None:
    assert "npm run build" in server.client.get("/").text
