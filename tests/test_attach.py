import asyncio
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from zwans.cli.attach import Attached, AttachError, _websocket_url, open_remote
from zwans.config import Config
from zwans.messages import TextBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.server.app import ServerSettings, create_app

TOKEN = "attach-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def server(tmp_path: Path) -> Iterator[str]:
    """A real server on a free port, in a thread, with a scripted model."""
    reply = ModelResponse(content=[TextBlock(text="Hi from the server.")], stop_reason="end_turn")
    script = [reply]
    settings = ServerSettings(
        config=Config(home=tmp_path / "home", subagents=False),
        env={},
        token=TOKEN,
        make_provider=lambda config, model: FakeProvider(script),
    )
    port = _free_port()
    config = uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error")
    runner = uvicorn.Server(config)
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    while not runner.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    runner.should_exit = True
    thread.join(5)


def test_attach_drives_a_session_the_browser_could_see_too(
    server: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = open_remote(server, TOKEN, None, tmp_path, "auto")
    session_id = str(status["id"])
    read_end, write_end = os.pipe()
    stdin = os.fdopen(read_end, encoding="utf-8")
    typed = os.fdopen(write_end, "w", encoding="utf-8")

    async def go() -> dict[str, object]:
        attached = asyncio.create_task(Attached(server, TOKEN, session_id, stdin).run())
        typed.write("Say hi.\n")
        typed.flush()
        async with httpx.AsyncClient(base_url=server) as client:
            headers = {"Authorization": f"Bearer {TOKEN}"}
            for _ in range(200):  # until the turn is over, as any other client would see it
                live = (await client.get(f"/api/sessions/{session_id}", headers=headers)).json()
                if live["turns"] == 1 and not live["running"]:
                    break
                await asyncio.sleep(0.05)
        typed.close()  # end of input detaches
        await asyncio.wait_for(attached, 5)
        return dict(live)

    live = asyncio.run(go())

    assert "Hi from the server." in capsys.readouterr().out
    assert live["title"] == "Say hi."


def test_attach_reports_a_wrong_token_and_a_missing_session(server: str, tmp_path: Path) -> None:
    with pytest.raises(AttachError, match="refused the token"):
        open_remote(server, "wrong", None, tmp_path, None)
    with pytest.raises(AttachError, match="No saved session"):
        open_remote(server, TOKEN, "20990101", tmp_path, None)
    with pytest.raises(AttachError, match="Can't reach"):
        open_remote("http://127.0.0.1:9", TOKEN, None, tmp_path, None)


def test_websocket_urls_follow_the_servers_scheme() -> None:
    assert _websocket_url("http://localhost:8765", "/x") == "ws://localhost:8765/x"
    assert _websocket_url("https://zwans.example", "/x") == "wss://zwans.example/x"
