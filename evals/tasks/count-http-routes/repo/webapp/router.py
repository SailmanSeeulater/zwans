"""Maps (method, path) to a handler.

Paths are normalised before they are stored: a trailing slash is dropped (except for "/"
itself) and `<name>` placeholders all become `<>`, so "/users/<id>/" and "/users/<user_id>"
are the same route. Registering a GET route also answers HEAD on the same path. Registering
the same method and path twice keeps the last handler.
"""

import re

PLACEHOLDER = re.compile(r"<[^>]*>")


def normalise(path: str) -> str:
    path = PLACEHOLDER.sub("<>", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return path or "/"


class Router:
    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], object] = {}

    def route(self, path: str, methods: tuple[str, ...] = ("GET",)):
        def register(handler):
            for method in methods:
                self.add(method, path, handler)
            return handler

        return register

    def add(self, method: str, path: str, handler) -> None:
        method = method.upper()
        self._routes[(method, normalise(path))] = handler
        if method == "GET":
            self._routes[("HEAD", normalise(path))] = handler

    def include(self, prefix: str, other: "Router") -> None:
        for (method, path), handler in other._routes.items():
            self.add(method, prefix.rstrip("/") + path, handler)

    def match(self, method: str, path: str):
        wanted = normalise(path).split("/")
        for (route_method, route_path), handler in self._routes.items():
            parts = route_path.split("/")
            if route_method != method.upper() or len(parts) != len(wanted):
                continue
            if all(part in ("<>", segment) for part, segment in zip(parts, wanted)):
                return handler
        return None
