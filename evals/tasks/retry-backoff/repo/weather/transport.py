"""The low-level way requests reach the weather service."""

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class TransportError(Exception):
    """A request that failed. status is the HTTP status, or None if no response came back."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Transport(Protocol):
    def get_json(self, path: str, params: dict[str, str]) -> Any: ...


class UrllibTransport:
    """The real transport. Not used by the tests."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_json(self, path: str, params: dict[str, str]) -> Any:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise TransportError(str(exc), status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TransportError(str(exc)) from exc
