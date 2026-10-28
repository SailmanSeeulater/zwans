"""Build HTTP requests for the API with the headers every call needs."""

from dataclasses import dataclass

DEFAULT_HEADERS = {
    "User-Agent": "acme-client/2.1",
    "Accept": "application/json",
}


@dataclass
class Request:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None = None


def build_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    token: str | None = None,
    body: bytes | None = None,
) -> Request:
    """Build a request with the default headers, plus auth and length when needed.

    Headers passed in win over the defaults. The caller's `headers` dict is not modified.
    """
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    if token:
        merged["Authorization"] = f"Bearer {token}"
    if body is not None:
        merged["Content-Length"] = str(len(body))
    return Request(method.upper(), url, merged, body)
