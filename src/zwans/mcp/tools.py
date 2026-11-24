"""MCP servers from the config, and their tools as Zwans tools.

    [mcp_servers.nextix]               # in ~/.zwans/config.toml
    command = "nextix"
    args = ["mcp"]
    env = { NEXTIX_REPO = "owner/name" }

    [mcp_servers.docs]
    url = "https://example.com/mcp"
    headers = { Authorization = "Bearer ${DOCS_TOKEN}" }

${NAME} in env and headers is filled in from the environment (or the .env file), so tokens
stay out of the config. Each tool is named mcp__<server>__<tool> and goes through the same
policy as every other tool. Servers come only from the user's config, never from a
workspace, because starting one runs a program.

A tool can bring a view for its results (MCP Apps, see apps.py). A tool only its views may
call (visibility ["app"]) isn't offered to the model, but stays here for them.
"""

import asyncio
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from zwans.config import McpServerConfig
from zwans.executor.local import command_env
from zwans.mcp import apps
from zwans.mcp.client import Connection, HttpConnection, McpError, StdioConnection
from zwans.tools.base import ToolContext, ToolError, ToolOutput

PREFIX = "mcp__"
VARIABLE = re.compile(r"\$\{(\w+)\}")
UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")  # the API's rule for tool names
MAX_NAME = 64


class McpInput(BaseModel):
    """Whatever the model sends. The server validates it against its own schema."""

    model_config = ConfigDict(extra="allow")


class McpTool:
    input_model = McpInput

    def __init__(
        self,
        server: str,
        connection: Connection,
        spec: dict[str, Any],
        timeout: float,
        views: apps.ViewCache | None = None,
    ):
        self.server = server
        self.remote_name = str(spec["name"])
        self.name = tool_name(server, self.remote_name)
        described = (spec.get("description") or "").strip() or f"The {self.remote_name} tool."
        self.description = f"From the {server} MCP server. {described}"
        schema = spec.get("inputSchema")
        self.input_schema = schema if isinstance(schema, dict) else {"type": "object"}
        # The server's own word, trusted because the user chose to run this server.
        annotations = spec.get("annotations") or {}
        self.read_only = annotations.get("readOnlyHint") is True
        self.connection = connection
        self.timeout = timeout
        self.spec = spec
        self.resource_uri = apps.resource_uri(spec)
        self.visibility = apps.visibility(spec)
        self.views = views

    async def run(self, args: McpInput, ctx: ToolContext) -> ToolOutput:
        arguments = args.model_dump()
        result = await self.call(arguments)
        output = ToolOutput(content=result_text(result), is_error=result.get("isError") is True)
        view = await self.view() if self.resource_uri else None
        if view is None:
            return output
        app = {
            "server": self.server,
            "tool": apps.tool_info(self.spec),
            "arguments": arguments,
            "result": apps.app_result(result),
            **view,
        }
        return ToolOutput(output.content, is_error=output.is_error, app=app)

    async def call(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """The server's whole CallToolResult, as a view is sent it."""
        try:
            return await self.connection.call_tool(self.remote_name, arguments, self.timeout)
        except McpError as exc:
            raise ToolError(str(exc)) from exc

    async def view(self) -> dict[str, Any] | None:
        if self.resource_uri is None or self.views is None:
            return None
        return await self.views.get(self.resource_uri)


def tool_name(server: str, tool: str) -> str:
    return UNSAFE_NAME.sub("_", f"{PREFIX}{server}__{tool}")[:MAX_NAME]


def result_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            resource = item.get("resource") or {}
            parts.append(str(resource.get("text") or f"[resource {resource.get('uri', '')}]"))
        elif kind == "resource_link":
            parts.append(f"[resource {item.get('uri', '')}: {item.get('name', '')}]")
        else:
            parts.append(f"[{kind} content, which Zwans can't show]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], indent=2))
    return "\n".join(parts) or "(no output)"


def expand(value: str, env: Mapping[str, str]) -> str:
    return VARIABLE.sub(lambda match: env.get(match.group(1), ""), value)


class McpServers:
    """The configured servers: started together, closed together."""

    def __init__(
        self,
        servers: Mapping[str, McpServerConfig],
        workspace: Path,
        env: Mapping[str, str],
        log_dir: Path,
    ) -> None:
        self.servers = dict(servers)
        self.workspace = workspace
        self.env = env
        self.log_dir = log_dir
        self.connections: list[Connection] = []
        # Every tool, by server and its own name, the ones only views may call included.
        self.tools: dict[tuple[str, str], McpTool] = {}

    async def start(self) -> tuple[list[McpTool], list[str]]:
        """Start every server and list its tools. Returns the tools the model may call, and a
        message for each server that didn't start, which is left out rather than stopping
        Zwans."""
        started = await asyncio.gather(*(self._start(name) for name in self.servers))
        tools: list[McpTool] = []
        problems: list[str] = []
        for outcome in started:
            if isinstance(outcome, str):
                problems.append(outcome)
            else:
                for tool in outcome:
                    self.tools[tool.server, tool.remote_name] = tool
                tools.extend(tool for tool in outcome if "model" in tool.visibility)
        return tools, problems

    def app_tool(self, server: str, name: str) -> McpTool | None:
        """A tool a view from `server` may call: one on the same server, open to views."""
        tool = self.tools.get((server, name))
        return tool if tool is not None and "app" in tool.visibility else None

    async def read_resource(self, server: str, uri: str) -> dict[str, Any]:
        """A resource a view from `server` asked for, from that server. Raises McpError."""
        connection = next((c for c in self.connections if c.name == server), None)
        if connection is None:
            raise McpError(f"There's no MCP server named {server}.")
        return await connection.read_resource(uri)

    async def _start(self, name: str) -> list[McpTool] | str:
        config = self.servers[name]
        connection = self._connection(name, config)
        self.connections.append(connection)
        try:
            await connection.start()
            specs = await connection.list_tools()
        except McpError as exc:
            return str(exc)
        views = apps.ViewCache(connection)
        return [McpTool(name, connection, spec, config.timeout, views) for spec in specs]

    def _connection(self, name: str, config: McpServerConfig) -> Connection:
        if config.url is not None:
            headers = {key: expand(value, self.env) for key, value in config.headers.items()}
            return HttpConnection(name, expand(config.url, self.env), headers)
        assert config.command is not None
        env = {**command_env(), **{k: expand(v, self.env) for k, v in config.env.items()}}
        return StdioConnection(
            name,
            config.command,
            config.args,
            env,
            cwd=self.workspace,
            log=self.log_dir / f"{name}.log",
        )

    async def close(self) -> None:
        await asyncio.gather(*(c.close() for c in self.connections), return_exceptions=True)
