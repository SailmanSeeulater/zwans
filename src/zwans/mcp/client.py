"""A client for MCP (Model Context Protocol) servers, over stdio or streamable HTTP.

MCP is JSON-RPC 2.0. The client opens with `initialize`, says `notifications/initialized`,
then lists the server's tools and calls them. Over stdio the server is a child process and
each message is one line of JSON on its stdin or stdout. Over HTTP every message is a POST;
the answer comes back as JSON or as a stream of server-sent events.
"""

import asyncio
import contextlib
import itertools
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

import httpx

from zwans import __version__
from zwans.executor.local import kill_tree, own_process_group

PROTOCOL_VERSION = "2025-06-18"
START_TIMEOUT = 30.0  # seconds for a server to start and answer `initialize`
MAX_LINE_BYTES = 64 * 1024 * 1024  # a big tool result arrives as one line over stdio

METHOD_NOT_FOUND = -32601


class McpError(Exception):
    pass


type JsonObject = dict[str, Any]


class Connection(ABC):
    """One MCP server. Use `start()` first and `close()` when done."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.server_info: JsonObject = {}
        self.protocol_version = PROTOCOL_VERSION
        self._ids = itertools.count(1)

    async def start(self) -> None:
        await self._open()
        params = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "zwans", "version": __version__},
        }
        result = await self.request("initialize", params, START_TIMEOUT)
        self.server_info = result.get("serverInfo") or {}
        self.protocol_version = result.get("protocolVersion") or PROTOCOL_VERSION
        await self.notify("notifications/initialized")

    async def list_tools(self) -> list[JsonObject]:
        tools: list[JsonObject] = []
        cursor: str | None = None
        while True:
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, name: str, arguments: JsonObject, timeout: float) -> JsonObject:
        return await self.request("tools/call", {"name": name, "arguments": arguments}, timeout)

    async def request(self, method: str, params: JsonObject, timeout: float = 60) -> JsonObject:
        request_id = next(self._ids)
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        try:
            reply = await asyncio.wait_for(self._exchange(message), timeout)
        except TimeoutError:
            raise McpError(f"{self.name} didn't answer {method} within {timeout:g}s") from None
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise McpError(f"{self.name}: {error.get('message', 'unknown error')}")
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    async def notify(self, method: str, params: JsonObject | None = None) -> None:
        message: JsonObject = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        await self._send_notification(message)

    @staticmethod
    def answer(message: JsonObject) -> JsonObject:
        """Our reply to a request the server sent us. Zwans offers the server no features, so
        only ping gets a real answer."""
        if message.get("method") == "ping":
            return {"jsonrpc": "2.0", "id": message["id"], "result": {}}
        error = {"code": METHOD_NOT_FOUND, "message": f"Zwans doesn't support {message['method']}"}
        return {"jsonrpc": "2.0", "id": message["id"], "error": error}

    @abstractmethod
    async def _open(self) -> None: ...

    @abstractmethod
    async def _exchange(self, message: JsonObject) -> JsonObject:
        """Send a request and return the server's reply to it."""

    @abstractmethod
    async def _send_notification(self, message: JsonObject) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class StdioConnection(Connection):
    def __init__(
        self,
        name: str,
        command: str,
        args: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        log: Path | None = None,
    ) -> None:
        super().__init__(name)
        self.argv = [command, *args]
        self.env = dict(env)
        self.cwd = cwd
        self.log = log  # where the server's stderr goes
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._write_lock = asyncio.Lock()
        self._log_file: IO[bytes] | None = None
        self._exited = ""  # why the server stopped answering, once it has

    async def _open(self) -> None:
        stderr: IO[bytes] | int = asyncio.subprocess.DEVNULL
        if self.log is not None:
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self.log.open("ab")
            stderr = self._log_file
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
                env=self.env,
                cwd=self.cwd,
                limit=MAX_LINE_BYTES,
                **own_process_group(),  # Ctrl+C stops the turn, not the server
            )
        except OSError as exc:
            raise McpError(f"{self.name}: couldn't start {self.argv[0]}: {exc}") from exc
        self._reader = asyncio.create_task(self._read())

    async def _exchange(self, message: JsonObject) -> JsonObject:
        if self._exited:
            raise McpError(f"{self.name}: {self._exited}")
        future: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._pending[message["id"]] = future
        try:
            await self._write(message)
            return await future
        finally:
            self._pending.pop(message["id"], None)

    async def _send_notification(self, message: JsonObject) -> None:
        await self._write(message)

    async def _write(self, message: JsonObject) -> None:
        assert self._process is not None and self._process.stdin is not None
        async with self._write_lock:
            try:
                self._process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise McpError(f"{self.name}: the server stopped") from exc

    async def _read(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        try:
            while line := await self._process.stdout.readline():
                try:
                    message = json.loads(line)
                except ValueError:
                    continue  # a server that prints a stray line; ignore it
                if isinstance(message, dict):
                    await self._dispatch(message)
            code = await self._process.wait()
            self._exited = f"the server exited with code {code}"
            if self.log is not None:
                self._exited += f"; its log is {self.log}"
        except (ValueError, asyncio.LimitOverrunError):
            self._exited = "the server sent a message too big to read"
        finally:
            self._exited = self._exited or "the server stopped"
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(McpError(f"{self.name}: {self._exited}"))

    async def _dispatch(self, message: JsonObject) -> None:
        if "method" in message:
            if "id" in message:  # a request from the server
                await self._write(self.answer(message))
            return  # notifications, such as log messages, aren't used
        future = self._pending.get(message.get("id"))  # type: ignore[arg-type]
        if future is not None and not future.done():
            future.set_result(message)

    async def close(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()  # the spec's way to ask a stdio server to exit
            try:
                await asyncio.wait_for(process.wait(), 2)
            except TimeoutError:
                await kill_tree(process)
        if self._reader is not None:
            self._reader.cancel()
        if self._log_file is not None:
            self._log_file.close()


class HttpConnection(Connection):
    def __init__(
        self,
        name: str,
        url: str,
        headers: Mapping[str, str],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(name)
        self.url = url
        self.headers = dict(headers)
        self.session_id: str | None = None
        self._client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(None))

    async def _open(self) -> None:
        pass  # nothing to open: each message is its own request

    def _request_headers(self) -> dict[str, str]:
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.session_id is not None:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    async def _exchange(self, message: JsonObject) -> JsonObject:
        try:
            async with self._client.stream(
                "POST", self.url, json=message, headers=self._request_headers()
            ) as response:
                self._check(response)
                content_type = response.headers.get("content-type", "")
                if content_type.startswith("text/event-stream"):
                    async for event in _server_sent_events(response.aiter_lines()):
                        reply = await self._handle(event, message["id"])
                        if reply is not None:
                            return reply
                else:
                    body = json.loads(await response.aread())
                    for item in body if isinstance(body, list) else [body]:
                        reply = await self._handle(item, message["id"])
                        if reply is not None:
                            return reply
        except httpx.HTTPError as exc:
            raise McpError(f"{self.name}: {exc}") from exc
        except ValueError as exc:
            raise McpError(f"{self.name}: the server sent something that isn't JSON") from exc
        raise McpError(f"{self.name}: the server didn't answer {message['method']}")

    async def _handle(self, item: Any, request_id: int) -> JsonObject | None:
        if not isinstance(item, dict):
            return None
        if "method" in item:
            if "id" in item:
                await self._post(self.answer(item))
            return None
        return item if item.get("id") == request_id else None

    async def _send_notification(self, message: JsonObject) -> None:
        await self._post(message)

    async def _post(self, message: JsonObject) -> None:
        try:
            response = await self._client.post(
                self.url, json=message, headers=self._request_headers()
            )
        except httpx.HTTPError as exc:
            raise McpError(f"{self.name}: {exc}") from exc
        self._check(response)

    def _check(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise McpError(f"{self.name}: HTTP {response.status_code} from {self.url}")
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self.session_id = session_id

    async def close(self) -> None:
        if self.session_id is not None:  # tell the server it can forget this session
            with contextlib.suppress(httpx.HTTPError):
                await self._client.delete(self.url, headers=self._request_headers(), timeout=5)
        await self._client.aclose()


async def _server_sent_events(lines: AsyncIterator[str]) -> AsyncIterator[Any]:
    """The JSON in each event's data lines."""
    data: list[str] = []
    async for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
        elif not line and data:
            yield json.loads("\n".join(data))
            data = []
    if data:
        yield json.loads("\n".join(data))
