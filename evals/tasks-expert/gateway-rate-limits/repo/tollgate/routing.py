"""Matching a request's path to a route."""

from dataclasses import dataclass

from tollgate.config import Route


@dataclass(frozen=True)
class Match:
    route: Route | None
    method_allowed: bool = True

    @property
    def found(self) -> bool:
        return self.route is not None


def normalize(path: str) -> str:
    """Collapse repeated slashes and drop a trailing one; keep the query string as is."""
    path, _, query = path.partition("?")
    parts = [part for part in path.split("/") if part]
    clean = "/" + "/".join(parts)
    return clean + ("?" + query if query else "")


def covers(prefix: str, path: str) -> bool:
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


class Router:
    def __init__(self, routes: list[Route]) -> None:
        # Longest prefix first, so the first route that covers a path is the best one.
        self.routes = sorted(routes, key=lambda route: len(route.prefix), reverse=True)

    def match(self, method: str, path: str) -> Match:
        bare = normalize(path).partition("?")[0]
        for route in self.routes:
            if covers(route.prefix, bare):
                return Match(route, route.allows(method))
        return Match(None)

    def upstream_path(self, route: Route, path: str) -> str:
        clean = normalize(path)
        if not route.strip_prefix or route.prefix == "/":
            return clean
        bare, _, query = clean.partition("?")
        rest = bare[len(route.prefix) :] or "/"
        return rest + ("?" + query if query else "")
