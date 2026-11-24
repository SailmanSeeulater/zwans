"""The Http tool: send a request to a server on this machine or the local network, as the
project's own API while it runs, and see the reply.

WebFetch reaches only the public web, so as not to be pointed at a local server by a page.
This is the other half: only local addresses, for trying out what is being built. curl
through Bash does it too, but its output mixes progress and headers into the body, and a
JSON reply comes back on one line. Here a reply comes back as its status, the headers that
matter, and its body, JSON laid out to read.

The policy judges a call as a network request to its host, so `Http(localhost)` allows them.
"""

import ipaddress
import json
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.web_local import Resolver, host_of, resolve

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
TIMEOUT = 30.0
MAX_BODY_CHARS = 20_000
SHOWN_HEADERS = (
    "content-type",
    "content-length",
    "location",
    "set-cookie",
    "www-authenticate",
    "cache-control",
    "access-control-allow-origin",
    "retry-after",
)


class HttpInput(BaseModel):
    url: str = Field(description='The address, as "http://localhost:8000/api/items".')
    method: Method = Field(default="GET", description="The HTTP method.")
    headers: dict[str, str] = Field(default={}, description="Headers to send.")
    json_body: Any = Field(
        default=None,
        alias="json",
        description="A JSON body to send, as an object or list; sets Content-Type.",
    )
    body: str | None = Field(default=None, description="A body to send as it is, instead.")

    model_config = {"populate_by_name": True}


class HttpTool:
    name = "Http"
    description = (
        "Send an HTTP request to a server on this machine or the local network, such as the "
        "app you're building while it runs, and get the status, the headers that matter and "
        "the body, with JSON laid out. Only local addresses: use WebFetch for the web."
    )
    input_model = HttpInput
    read_only = False  # a request can change what the server holds

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None = None, resolver: Resolver = resolve
    ) -> None:
        self.transport = transport
        self.resolver = resolver

    def host(self, args: dict[str, Any]) -> str:
        return host_of(args.get("url"))

    async def run(self, args: HttpInput, ctx: ToolContext) -> ToolOutput:
        url = args.url.strip()
        host = host_of(url)
        if not host:
            raise ToolError(f"{url!r} isn't an address Http can use: it needs http or https.")
        await self._check_local(host)
        if args.json_body is not None and args.body is not None:
            raise ToolError("Send json or body, not both.")
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT) as client:
                reply = await client.request(
                    args.method,
                    url,
                    headers=args.headers,
                    json=args.json_body,
                    content=args.body,
                )
        except httpx.ConnectError as exc:
            port = urlsplit(url).port
            where = f"on port {port}" if port else "there"
            raise ToolError(
                f"Nothing answered at {url} ({exc or 'connection refused'}): is the server "
                f"running {where}?"
            ) from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"The request failed: {exc or type(exc).__name__}") from exc
        took = (time.monotonic() - started) * 1000
        lines = [f"HTTP {reply.status_code} {reply.reason_phrase} ({took:.0f} ms)"]
        for name in SHOWN_HEADERS:
            for value in reply.headers.get_list(name):
                lines.append(f"{name}: {value}")
        body = _body(reply)
        lines += ["", body] if body else []
        return ToolOutput(content="\n".join(lines), is_error=reply.status_code >= 500)

    async def _check_local(self, host: str) -> None:
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                addresses = await self.resolver(host)
            except OSError as exc:
                raise ToolError(f"Couldn't find {host}: {exc}") from exc
        if not addresses or any(_is_public(address) for address in addresses):
            raise ToolError(
                f"{host} is on the public internet, and Http only reaches this machine and "
                "the local network. Use WebFetch to read a page on the web."
            )


def _is_public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return True


def _body(reply: httpx.Response) -> str:
    if not reply.content:
        return ""
    kind = reply.headers.get("content-type", "").split(";")[0].strip().lower()
    if kind.endswith("json") or kind.endswith("+json"):
        try:
            text = json.dumps(reply.json(), indent=2, ensure_ascii=False)
        except ValueError:
            text = reply.text
    elif kind.startswith("text/") or kind in ("application/xml", "application/javascript", ""):
        text = reply.text
        if not kind and b"\x00" in reply.content[:1024]:
            return f"({len(reply.content):,} bytes of binary data)"
    else:
        return f"({len(reply.content):,} bytes of {kind})"
    if len(text) > MAX_BODY_CHARS:
        cut = len(text) - MAX_BODY_CHARS
        text = text[:MAX_BODY_CHARS] + f"\n[... {cut:,} more characters]"
    return text
