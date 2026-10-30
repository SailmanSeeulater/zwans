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

    def __init__(self, server: str, connection: Connection, spec: dict[str, Any], timeout: float):
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

    async def run(self, args: McpInput, ctx: ToolContext) -> ToolOutput:
        try:
            result = await self.connection.call_tool(
                self.remote_name, args.model_dump(), self.timeout
            )
        except McpError as exc:
            raise ToolError(str(exc)) from exc
        return ToolOutput(content=result_text(result), is_error=result.get("isError") is True)


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

    async def start(self) -> tuple[list[McpTool], list[str]]:
        """Start every server and list its tools. Returns the tools, and a message for each
        server that didn't start, which is left out rather than stopping Zwans."""
        started = await asyncio.gather(*(self._start(name) for name in self.servers))
        tools: list[McpTool] = []
        problems: list[str] = []
        for outcome in started:
            if isinstance(outcome, str):
                problems.append(outcome)
            else:
                tools.extend(outcome)
        return tools, problems

    async def _start(self, name: str) -> list[McpTool] | str:
        config = self.servers[name]
        connection = self._connection(name, config)
        self.connections.append(connection)
        try:
            await connection.start()
            specs = await connection.list_tools()
        except McpError as exc:
            return str(exc)
        return [McpTool(name, connection, spec, config.timeout) for spec in specs]

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
