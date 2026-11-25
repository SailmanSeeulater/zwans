"""The services behind the gateway. In production these are HTTP clients; here, anything
with a handle(request) method will do."""

from typing import Protocol

from tollgate.http import Request, Response


class Upstream(Protocol):
    def handle(self, request: Request) -> Response: ...


class EchoUpstream:
    """Answers every request with what it received. Handy for replays and smoke tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.seen = 0

    def handle(self, request: Request) -> Response:
        self.seen += 1
        return Response.json_body(
            200, {"upstream": self.name, "method": request.method, "path": request.path}
        )


class StaticUpstream:
    """Always gives the same response."""

    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        self.status = status
        self.body = body

    def handle(self, request: Request) -> Response:
        return Response(self.status, {}, self.body)


class FailingUpstream:
    """An upstream that is down."""

    def __init__(self, message: str = "connection refused") -> None:
        self.message = message

    def handle(self, request: Request) -> Response:
        raise ConnectionError(self.message)
