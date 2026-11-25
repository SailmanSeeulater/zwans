"""Connecting only to the public address that was checked, for WebFetch.

WebFetch refuses to reach this machine or the local network. Checking a host's addresses and
then letting the HTTP client look the host up again to connect leaves a gap: a name server
that answers with a public address the first time and 127.0.0.1 the second (DNS rebinding)
gets a request through to a server the check would have refused. So the lookup, the check
and the connection happen in one place here: the network backend resolves the host, refuses
it unless every address is public, and connects to the address it checked. TLS still checks
the certificate against the host's name, which httpcore takes from the request, not from the
address.
"""

import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from typing import Any

import httpcore
import httpx

type Resolver = Callable[[str], Awaitable[list[str]]]


def is_public(address: str) -> bool:
    try:
        return ipaddress.ip_address(address.split("%")[0]).is_global
    except ValueError:
        return False


async def public_addresses(host: str, resolver: Resolver) -> list[str]:
    """The addresses `host` stands for, when every one is public. Raises PrivateAddress
    otherwise, or OSError when the name can't be found."""
    try:
        addresses = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        addresses = await resolver(host)
    if not addresses or not all(is_public(address) for address in addresses):
        raise PrivateAddress(host)
    return addresses


class PrivateAddress(Exception):
    def __init__(self, host: str) -> None:
        super().__init__(
            f"{host} isn't a public address, and WebFetch only reaches the public web. For a "
            "server on this machine or your network, use Bash with curl."
        )
        self.host = host


class PublicOnly(httpcore.AsyncNetworkBackend):
    """A network backend that connects only to a host's checked public address."""

    def __init__(self, resolver: Resolver, inner: httpcore.AsyncNetworkBackend | None = None):
        self.resolver = resolver
        self.inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await public_addresses(host, self.resolver)
        except (PrivateAddress, OSError) as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return await self.inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("WebFetch doesn't connect to local sockets.")

    async def sleep(self, seconds: float) -> None:
        await self.inner.sleep(seconds)


class PinnedTransport(httpx.AsyncBaseTransport):
    """An httpx transport whose connections go through PublicOnly."""

    def __init__(
        self, resolver: Resolver, inner: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(),
            network_backend=PublicOnly(resolver, inner),
            max_connections=10,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        core = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=url.raw_scheme, host=url.raw_host, port=url.port, target=url.raw_path
            ),
            headers=request.headers.raw,
            content=request.stream,  # an async stream of bytes
            extensions=request.extensions,
        )
        try:
            reply = await self.pool.handle_async_request(core)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=request) from exc
        except httpcore.NetworkError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        except (httpcore.ProtocolError, httpcore.UnsupportedProtocol) as exc:
            raise httpx.TransportError(str(exc), request=request) from exc
        return httpx.Response(
            status_code=reply.status,
            headers=reply.headers,
            stream=_Body(reply.stream, request),
            extensions=reply.extensions,
        )

    async def aclose(self) -> None:
        await self.pool.aclose()


class _Body(httpx.AsyncByteStream):
    def __init__(self, stream: Any, request: httpx.Request) -> None:
        self.stream = stream
        self.request = request

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for part in self.stream:
                yield part
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=self.request) from exc
        except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise httpx.ReadError(str(exc), request=self.request) from exc

    async def aclose(self) -> None:
        close = getattr(self.stream, "aclose", None)
        if close is not None:
            await close()


async def resolve(host: str) -> list[str]:
    """Every address a host name stands for."""
    import asyncio

    found = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in found})
