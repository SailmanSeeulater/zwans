import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from zwans.config import Config, McpServerConfig
from zwans.executor.local import LocalExecutor
from zwans.mcp.client import HttpConnection
from zwans.mcp.tools import McpInput, McpServers, McpTool, expand, result_text, tool_name
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, input_schema

FAKE_SERVER = Path(__file__).parent / "fake_mcp_server.py"


def fake_server(**overrides: Any) -> McpServerConfig:
    return McpServerConfig(command=sys.executable, args=[str(FAKE_SERVER)], **overrides)


def with_servers[T](
    tmp_path: Path,
    servers: dict[str, McpServerConfig],
    body: Callable[[dict[str, McpTool], list[str]], Awaitable[T]],
    env: dict[str, str] | None = None,
) -> T:
    async def go() -> T:
        manager = McpServers(servers, tmp_path, env or {}, tmp_path / "logs")
        try:
            tools, problems = await manager.start()
            return await body({tool.name: tool for tool in tools}, problems)
        finally:
            await manager.close()

    return asyncio.run(go())


async def call(tool: McpTool, tmp_path: Path, **args: Any) -> tuple[str, bool]:
    output = await tool.run(McpInput(**args), ToolContext(executor=LocalExecutor(tmp_path)))
    return output.content, output.is_error


def test_a_stdio_servers_tools_become_zwans_tools(tmp_path: Path) -> None:
    async def body(tools: dict[str, McpTool], problems: list[str]) -> None:
        assert problems == []
        assert sorted(tools) == [
            "mcp__fake__echo",
            "mcp__fake__env",
            "mcp__fake__fail",
            "mcp__fake__ping_me",
            "mcp__fake__quit",
            "mcp__fake__slow",
        ]  # both pages of tools/list
        echo = tools["mcp__fake__echo"]
        assert echo.read_only
        assert not tools["mcp__fake__fail"].read_only
        assert echo.description == "From the fake MCP server. Return the text."
        assert input_schema(echo)["required"] == ["text"]
        assert await call(echo, tmp_path, text="hello") == ("hello", False)
        assert await call(tools["mcp__fake__fail"], tmp_path) == ("That didn't work.", True)

    with_servers(tmp_path, {"fake": fake_server()}, body)


def test_calls_can_overlap_and_the_server_can_ping_the_client(tmp_path: Path) -> None:
    async def body(tools: dict[str, McpTool], problems: list[str]) -> None:
        slow, echo = tools["mcp__fake__slow"], tools["mcp__fake__echo"]
        results = await asyncio.gather(
            call(slow, tmp_path, seconds=0.5), call(echo, tmp_path, text="quick")
        )
        assert list(results) == [("finally", False), ("quick", False)]
        content, _ = await call(tools["mcp__fake__ping_me"], tmp_path)
        assert content == "client answered: {}"

    with_servers(tmp_path, {"fake": fake_server()}, body)


def test_a_slow_call_times_out_and_a_dead_server_is_an_error(tmp_path: Path) -> None:
    async def body(tools: dict[str, McpTool], problems: list[str]) -> None:
        with pytest.raises(ToolError, match=r"didn't answer tools/call within 0\.3s"):
            await call(tools["mcp__fake__slow"], tmp_path, seconds=5)
        with pytest.raises(ToolError, match="exited with code 3"):
            await call(tools["mcp__fake__quit"], tmp_path)
        with pytest.raises(ToolError, match="exited with code 3"):
            await call(tools["mcp__fake__echo"], tmp_path, text="anyone?")

    with_servers(tmp_path, {"fake": fake_server(timeout=0.3)}, body)


def test_a_server_that_wont_start_is_skipped_with_a_message(tmp_path: Path) -> None:
    servers = {
        "broken": McpServerConfig(command="definitely-not-a-program-zwans"),
        "fake": fake_server(),
    }

    async def body(tools: dict[str, McpTool], problems: list[str]) -> None:
        assert "mcp__fake__echo" in tools
        [problem] = problems
        assert problem.startswith("broken: couldn't start definitely-not-a-program-zwans")

    with_servers(tmp_path, servers, body)


def test_server_env_fills_in_variables_and_never_gets_zwans_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    server = fake_server(env={"NEXTIX_REPO": "${REPO}"})

    async def body(tools: dict[str, McpTool], problems: list[str]) -> None:
        env = tools["mcp__fake__env"]
        assert await call(env, tmp_path, name="NEXTIX_REPO") == ("owner/name", False)
        assert await call(env, tmp_path, name="ANTHROPIC_API_KEY") == ("(unset)", False)

    with_servers(tmp_path, {"fake": server}, body, env={"REPO": "owner/name"})


def test_a_server_needs_exactly_one_of_command_and_url() -> None:
    with pytest.raises(ValidationError, match="either command"):
        McpServerConfig()
    with pytest.raises(ValidationError, match="either command"):
        McpServerConfig(command="x", url="https://example.com/mcp")
    config = Config.model_validate({"mcp_servers": {"nextix": {"command": "nextix"}}})
    assert config.mcp_servers["nextix"].args == []


def test_names_results_and_variables() -> None:
    assert tool_name("my server", "do.it") == "mcp__my_server__do_it"
    assert len(tool_name("s", "x" * 200)) == 64
    assert expand("Bearer ${TOKEN}", {"TOKEN": "abc"}) == "Bearer abc"
    assert expand("${MISSING}", {}) == ""
    mixed = {
        "content": [
            {"type": "text", "text": "one"},
            {"type": "image", "data": "...", "mimeType": "image/png"},
            {"type": "resource", "resource": {"uri": "file:///a", "text": "two"}},
        ]
    }
    assert result_text(mixed) == "one\n[image content, which Zwans can't show]\ntwo"
    assert result_text({"structuredContent": {"n": 1}}) == '{\n  "n": 1\n}'
    assert result_text({}) == "(no output)"


# -- streamable HTTP


class FakeHttpServer:
    """Answers initialize with JSON and a session id, tools/list as an event stream that
    pings the client first, and tools/call with JSON."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, dict[str, str], Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        self.seen.append((request.method, dict(request.headers), body))
        if request.method == "DELETE":
            return httpx.Response(200)
        if body is None or "id" not in body or "method" not in body:
            return httpx.Response(202)  # a notification, or our answer to the ping
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "serverInfo": {"name": "http"}}
            reply = {"jsonrpc": "2.0", "id": body["id"], "result": result}
            return httpx.Response(200, json=reply, headers={"Mcp-Session-Id": "s-123"})
        if method == "tools/list":
            tool = {"name": "search", "inputSchema": {"type": "object"}}
            events = [
                {"jsonrpc": "2.0", "id": 99, "method": "ping"},
                {"jsonrpc": "2.0", "method": "notifications/message", "params": {}},
                {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [tool]}},
            ]
            stream = "".join(f"event: message\ndata: {json.dumps(e)}\n\n" for e in events)
            return httpx.Response(200, text=stream, headers={"content-type": "text/event-stream"})
        found = f"found {body['params']['arguments']}"
        content = {"content": [{"type": "text", "text": found}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": content})


def test_an_http_server_speaks_json_and_event_streams(tmp_path: Path) -> None:
    server = FakeHttpServer()

    async def go() -> None:
        connection = HttpConnection(
            "docs",
            "https://mcp.example/mcp",
            {"Authorization": "Bearer t"},
            transport=httpx.MockTransport(server),
        )
        await connection.start()
        [spec] = await connection.list_tools()
        tool = McpTool("docs", connection, spec, timeout=5)
        assert await call(tool, tmp_path, q="zwans") == ("found {'q': 'zwans'}", False)
        await connection.close()

    asyncio.run(go())

    methods = [(m, b.get("method") if b else None) for m, _, b in server.seen]
    assert methods == [
        ("POST", "initialize"),
        ("POST", "notifications/initialized"),
        ("POST", "tools/list"),
        ("POST", None),  # our answer to the server's ping
        ("POST", "tools/call"),
        ("DELETE", None),
    ]
    _, first, _ = server.seen[0]
    assert "mcp-session-id" not in first
    assert first["authorization"] == "Bearer t"
    for _, headers, _ in server.seen[1:]:
        assert headers["mcp-session-id"] == "s-123"
        assert headers["mcp-protocol-version"] == "2025-03-26"
        assert headers["accept"] == "application/json, text/event-stream"
    _, _, pong = server.seen[3]
    assert pong == {"jsonrpc": "2.0", "id": 99, "result": {}}


def test_an_http_error_is_reported(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async def go() -> list[McpTool] | str:
        manager = McpServers({}, tmp_path, {}, tmp_path)
        connection = HttpConnection("docs", "https://x/mcp", {}, httpx.MockTransport(refuse))
        manager.connections.append(connection)
        try:
            await connection.start()
        except Exception as exc:
            return str(exc)
        finally:
            await manager.close()
        return []

    assert asyncio.run(go()) == "docs: HTTP 401 from https://x/mcp"


# -- the policy


def mcp_permissions(tmp_path: Path, **file: Any) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(**file), "test")
    executor = LocalExecutor(tmp_path)
    return Permissions(policy, executor.contains, executor.relative)


class FakeMcpTool:
    def __init__(self, name: str, read_only: bool) -> None:
        self.name, self.read_only = name, read_only


def test_mcp_tools_ask_unless_read_only_even_in_auto_mode(tmp_path: Path) -> None:
    perms = mcp_permissions(tmp_path, mode="auto")
    comment = FakeMcpTool("mcp__nextix__comment_on_ticket", read_only=False)
    listing = FakeMcpTool("mcp__nextix__list_tickets", read_only=True)

    verdict = perms.check(comment, {"ticket": "12"})
    assert verdict.decision == Decision.ASK
    assert verdict.reason == (
        "mcp__nextix__comment_on_ticket can change things outside the workspace"
    )
    assert verdict.rules == ("mcp__nextix__comment_on_ticket",)
    assert perms.check(listing, {}).decision == Decision.ALLOW
    read_only = mcp_permissions(tmp_path, mode="read-only")
    assert read_only.check(comment, {}).decision == Decision.DENY


def test_an_allowed_mcp_tool_asks_again_after_untrusted_content(tmp_path: Path) -> None:
    perms = mcp_permissions(tmp_path, allow=["mcp__nextix__comment_on_ticket"])
    comment = FakeMcpTool("mcp__nextix__comment_on_ticket", read_only=False)
    assert perms.check(comment, {}).decision == Decision.ALLOW

    assert perms.observe("mcp__nextix__get_ticket", is_error=False)  # its output is untrusted

    verdict = perms.check(comment, {})
    assert verdict.decision == Decision.ASK
    assert "after untrusted content was read" in verdict.reason
