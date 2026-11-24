"""MCP Apps: tools with views (src/zwans/mcp/apps.py), from the fake server's chart tool."""

import asyncio
import base64
import json
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from test_mcp import fake_server
from test_server import AUTH, Server, connect, handshake, say, until

from zwans.executor.local import LocalExecutor
from zwans.mcp.apps import resource_uri, view_from, visibility
from zwans.mcp.client import APP_MIME_TYPE, APPS_EXTENSION
from zwans.mcp.tools import McpInput, McpServers
from zwans.messages import ToolUseBlock
from zwans.providers.base import ModelResponse
from zwans.providers.fake import FakeProvider
from zwans.tools.base import ToolContext

VIEW_URI = "ui://fake/chart.html"


def test_a_tool_with_a_view_sends_it_with_its_result(tmp_path: Path) -> None:
    async def go() -> None:
        manager = McpServers({"fake": fake_server()}, tmp_path, {}, tmp_path / "logs")
        try:
            tools = {tool.name: tool for tool in (await manager.start())[0]}
            ctx = ToolContext(executor=LocalExecutor(tmp_path))
            chart = tools["mcp__fake__chart"]
            output = await chart.run(McpInput(numbers=[5, 7]), ctx)
            again = await chart.run(McpInput(numbers=[1]), ctx)
            plain = await tools["mcp__fake__echo"].run(McpInput(text="hi"), ctx)
            client = await tools["mcp__fake__client"].run(McpInput(), ctx)
        finally:
            await manager.close()

        assert output.content == "numbers: [5, 7]"  # what the model sees
        assert output.app == {
            "server": "fake",
            "tool": {
                "name": "chart",
                "description": "Chart the numbers.",
                "inputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": True},
                "_meta": {"ui": {"resourceUri": VIEW_URI}},
            },
            "arguments": {"numbers": [5, 7]},
            "result": {
                "content": [{"type": "text", "text": "numbers: [5, 7]"}],
                "structuredContent": {"numbers": [5, 7]},
            },
            "uri": VIEW_URI,
            "html": "<!doctype html><title>Chart</title><script>/* draws the numbers */</script>",
            # The origin that tried to add a directive of its own is dropped.
            "csp": {"resourceDomains": ["https://cdn.example.com"]},
            "permissions": ["clipboardWrite"],
            "prefers_border": False,
        }
        assert again.app is not None and again.app["arguments"] == {"numbers": [1]}
        assert plain.app is None
        seen = json.loads(client.content)
        assert seen["reads"] == 1  # the view was read once, for both calls
        extension = seen["capabilities"]["extensions"][APPS_EXTENSION]
        assert extension == {"mimeTypes": [APP_MIME_TYPE]}

    asyncio.run(go())


def test_views_may_call_only_their_own_servers_tools_open_to_them(tmp_path: Path) -> None:
    async def go() -> None:
        manager = McpServers({"fake": fake_server()}, tmp_path, {}, tmp_path / "logs")
        try:
            await manager.start()
            shuffle = manager.app_tool("fake", "shuffle")
            assert shuffle is not None
            assert await shuffle.call({"numbers": [1, 2, 3]}) == {
                "content": [{"type": "text", "text": "numbers: [3, 2, 1]"}],
                "structuredContent": {"numbers": [3, 2, 1]},
            }
            assert manager.app_tool("fake", "chart") is not None  # both, by default
            assert manager.app_tool("fake", "secret") is None  # only the model's
            assert manager.app_tool("other", "shuffle") is None
            read = await manager.read_resource("fake", VIEW_URI)
            assert read["contents"][0]["mimeType"] == APP_MIME_TYPE
        finally:
            await manager.close()

    asyncio.run(go())


def test_reading_tool_meta() -> None:
    assert resource_uri({"_meta": {"ui": {"resourceUri": "ui://a/b"}}}) == "ui://a/b"
    assert resource_uri({"_meta": {"ui/resourceUri": "ui://old"}}) == "ui://old"  # deprecated
    assert resource_uri({"_meta": {"ui": {"resourceUri": "https://x"}}}) is None
    assert resource_uri({"name": "plain"}) is None
    assert visibility({}) == {"model", "app"}
    assert visibility({"_meta": {"ui": {"visibility": ["app", "bogus"]}}}) == {"app"}


def test_reading_a_view() -> None:
    html = "<p>hi</p>"
    blob = {
        "uri": "ui://v",
        "mimeType": "text/html; profile=mcp-app",
        "blob": base64.b64encode(html.encode()).decode(),
    }
    view = view_from("ui://v", {"contents": [blob]})
    assert view is not None and view["html"] == html
    assert view["csp"] == {} and view["permissions"] == [] and view["prefers_border"] is None
    # Plain HTML isn't an app's view, and nor is a resource that isn't the one asked for.
    assert view_from("ui://v", {"contents": [{**blob, "mimeType": "text/html"}]}) is None
    assert view_from("ui://v", {"contents": [{**blob, "uri": "ui://w"}]}) is None
    assert view_from("ui://v", {"contents": [{**blob, "blob": "not base64!"}]}) is None
    assert view_from("ui://v", {}) is None


# -- through the server, as the web UI uses it


def chart_call() -> ModelResponse:
    call = ToolUseBlock(id="c1", name="mcp__fake__chart", input={"numbers": [4, 2]})
    return ModelResponse(content=[call], stop_reason="tool_use")


def test_a_views_calls_go_through_the_policy_and_show_in_the_conversation(
    tmp_path: Path,
) -> None:
    server = Server(tmp_path, mcp_servers={"fake": fake_server()})
    with server.client:
        session_id = server.new_session(FakeProvider([chart_call(), say("Charted.")]), mode="ask")
        base = f"/api/sessions/{session_id}/apps"

        def app_call(name: str, numbers: list[int]) -> Future[Any]:
            body = {"server": "fake", "name": name, "arguments": {"numbers": numbers}}
            return pool.submit(lambda: server.client.post(f"{base}/call", json=body, headers=AUTH))

        with connect(server, session_id) as ws, ThreadPoolExecutor(1) as pool:
            handshake(ws)
            ws.send_json({"type": "prompt", "text": "Chart 4 and 2."})
            result = until(ws, "tool_result")[-1]  # read-only, so it ran without asking
            until(ws, "turn_ended")

            asked = app_call("shuffle", [1, 2])
            seen = until(ws, "permission_requested")
            ws.send_json({"type": "approve", "call_id": seen[-1]["call_id"], "answer": "once"})
            allowed = until(ws, "tool_result")[-1]

            refused = app_call("shuffle", [3])
            question = until(ws, "permission_requested")[-1]
            ws.send_json({"type": "approve", "call_id": question["call_id"], "answer": "no"})
            declined = until(ws, "tool_result")[-1]

            secret = app_call("secret", [])
            read = server.client.post(
                f"{base}/read", json={"server": "fake", "uri": VIEW_URI}, headers=AUTH
            )
            missing = server.client.post(
                f"{base}/read", json={"server": "nope", "uri": VIEW_URI}, headers=AUTH
            )

            assert asked.result().json() == {
                "content": [{"type": "text", "text": "numbers: [2, 1]"}],
                "structuredContent": {"numbers": [2, 1]},
            }
            assert refused.result().json()["isError"] is True
            no_secret = "The fake MCP server has no tool named secret for its views."
            assert secret.result().json() == {
                "content": [{"type": "text", "text": no_secret}],
                "isError": True,
            }

    assert result["app"]["html"].startswith("<!doctype html>")
    assert result["app"]["arguments"] == {"numbers": [4, 2]}
    assert result["app"]["result"]["structuredContent"] == {"numbers": [4, 2]}
    requested = [m for m in seen if m["type"] == "tool_call_requested"][-1]
    assert requested["by"] == "view" and requested["name"] == "mcp__fake__shuffle"
    assert requested["call_id"] == seen[-1]["call_id"]
    assert seen[-1]["reason"] == "mcp__fake__shuffle can change things outside the workspace"
    assert allowed["content"] == "numbers: [2, 1]" and allowed["untrusted"] is True
    assert allowed["app"] is None  # its result goes back to the view that asked
    assert declined["is_error"] is True
    assert read.json()["contents"][0]["uri"] == VIEW_URI
    assert missing.status_code == 502
