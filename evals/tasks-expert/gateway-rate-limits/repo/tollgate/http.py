"""The request and response types the gateway passes around."""

import json
from dataclasses import dataclass, field
from typing import Any


class Headers(dict[str, str]):
    """Header names are case-insensitive; values are kept as given."""

    def __init__(self, items: dict[str, str] | None = None) -> None:
        super().__init__()
        for name, value in (items or {}).items():
            self[name] = value

    def __setitem__(self, name: str, value: str) -> None:
        super().__setitem__(name.lower(), str(value))

    def __getitem__(self, name: str) -> str:
        return super().__getitem__(name.lower())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and super().__contains__(name.lower())

    def get(self, name: str, default: Any = None) -> Any:  # type: ignore[override]
        return super().get(name.lower(), default)


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        if not self.path.startswith("/"):
            self.path = "/" + self.path
        self.headers = Headers(self.headers)

    def header(self, name: str) -> str | None:
        value = self.headers.get(name)
        if value is None:
            return None
        value = value.strip()
        return value or None

    def with_path(self, path: str) -> "Request":
        return Request(self.method, path, dict(self.headers), self.body)


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        self.headers = Headers(self.headers)

    @classmethod
    def json_body(
        cls, status: int, payload: Any, headers: dict[str, str] | None = None
    ) -> "Response":
        merged = {"Content-Type": "application/json"}
        merged.update(headers or {})
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        return cls(status, merged, body)

    @classmethod
    def error(cls, status: int, message: str, headers: dict[str, str] | None = None) -> "Response":
        return cls.json_body(status, {"error": message}, headers)

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")
