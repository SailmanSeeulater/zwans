"""The web UI's permission toggle and /compact, over a session's WebSocket."""

from pathlib import Path
from typing import Any

from test_server import Server, connect, handshake, say, until, write

from zwans.providers.fake import FakeProvider


def mode_status(ws: Any, mode: str) -> dict[str, Any]:
    """The first status in that mode: the turn before may still send one of its own."""
    while True:
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == "status" and message["mode"] == mode:
            return message


def test_the_mode_changes_how_the_next_calls_are_judged(tmp_path: Path) -> None:
    server = Server(tmp_path)
    provider = FakeProvider(
        [write("a.txt", "1"), say("Couldn't."), write("a.txt", "2"), say("Done.")]
    )
    with server.client:
        session_id = server.new_session(provider, mode="ask")
        with connect(server, session_id) as ws:
            status, _ = handshake(ws)
            ws.send_json({"type": "mode", "mode": "read-only"})
            read_only = mode_status(ws, "read-only")
            ws.send_json({"type": "prompt", "text": "Write a.txt"})
            refused = until(ws, "turn_ended")
            ws.send_json({"type": "mode", "mode": "auto"})
            auto = mode_status(ws, "auto")
            ws.send_json({"type": "prompt", "text": "Write a.txt"})
            until(ws, "turn_ended")
            ws.send_json({"type": "mode", "mode": "yolo"})
            bad = until(ws, "server_error")[-1]

    assert status["mode"] == "ask"
    assert read_only["mode"] == "read-only"
    assert any(m["type"] == "permission_denied" for m in refused)
    assert auto["mode"] == "auto"
    assert (server.workspace / "a.txt").read_text() == "2"  # auto wrote it without asking
    assert "isn't a mode" in bad["message"]


def test_compact_summarizes_the_older_messages_on_request(tmp_path: Path) -> None:
    server = Server(tmp_path)
    # Six turns: the latest eight messages are kept word for word, and two must be left over.
    provider = FakeProvider([*(say(f"Reply {n}.") for n in range(6)), say("Summary of it all.")])
    with server.client:
        session_id = server.new_session(provider)
        with connect(server, session_id) as ws:
            handshake(ws)
            ws.send_json({"type": "compact"})
            early = until(ws, "server_error")[-1]
            for n in range(6):
                ws.send_json({"type": "prompt", "text": f"Message {n}"})
                until(ws, "turn_ended")
            ws.send_json({"type": "compact"})
            compacted = until(ws, "context_compacted")[-1]
            after = until(ws, "status")

    assert "Nothing to compact yet" in early["message"]
    assert "Summary of it all." in compacted["summary"]  # the fake model reports no token counts
    assert after[-1]["running"] is False
