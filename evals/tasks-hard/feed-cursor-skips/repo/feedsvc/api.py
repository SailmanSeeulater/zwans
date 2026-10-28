"""The HTTP API, as plain functions: handle(method, target, body) -> (status, json)."""

import json
import re
from urllib.parse import parse_qs, urlsplit

from feedsvc.cursor import CursorError
from feedsvc.models import ValidationError
from feedsvc.service import FeedService

Response = tuple[int, dict[str, object]]


def _error(status: int, message: str) -> Response:
    return status, {"error": message}


def _int_param(params: dict[str, list[str]], name: str) -> int | None:
    values = params.get(name)
    if not values:
        return None
    try:
        return int(values[-1])
    except ValueError:
        raise ValidationError(f"{name} must be a whole number") from None


def _param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[-1] if values else None


class Api:
    def __init__(self, service: FeedService) -> None:
        self.service = service

    def handle(self, method: str, target: str, body: str | None = None) -> Response:
        parts = urlsplit(target)
        params = parse_qs(parts.query, keep_blank_values=True)
        try:
            return self._route(method.upper(), parts.path.rstrip("/") or "/", params, body)
        except (ValidationError, CursorError) as exc:
            return _error(400, str(exc))
        except LookupError as exc:
            return _error(404, str(exc.args[0]) if exc.args else "not found")

    def _route(
        self, method: str, path: str, params: dict[str, list[str]], body: str | None
    ) -> Response:
        if method == "GET" and path == "/feed":
            user = _param(params, "user")
            if not user:
                raise ValidationError("user is required")
            page = _int_param(params, "page")
            if page is not None:
                # TODO: remove once app versions before 4.2 are gone.
                return 200, self.service.home_by_page(
                    user, page, _int_param(params, "limit")
                ).to_dict()
            feed = self.service.home(
                user, _param(params, "cursor") or None, _int_param(params, "limit")
            )
            return 200, feed.to_dict()

        if method == "GET" and path == "/feed/refresh":
            user, since = _param(params, "user"), _param(params, "since")
            if not user or not since:
                raise ValidationError("user and since are required")
            return 200, self.service.refresh(user, since).to_dict()

        match = re.fullmatch(r"/users/(\w+)/posts", path)
        if method == "GET" and match:
            page = self.service.profile(
                match.group(1), _param(params, "cursor") or None, _int_param(params, "limit")
            )
            return 200, page.to_dict()

        if method == "POST" and path == "/posts":
            data = self._json(body)
            post = self.service.publish(str(data.get("author", "")), str(data.get("body", "")))
            return 201, post.to_dict()

        match = re.fullmatch(r"/users/(\w+)/(follow|unfollow|mute|unmute)", path)
        if method == "POST" and match:
            data = self._json(body)
            action = getattr(self.service, match.group(2))
            action(match.group(1), str(data.get("user", "")))
            return 204, {}

        return _error(404, f"no route for {method} {path}")

    @staticmethod
    def _json(body: str | None) -> dict[str, object]:
        try:
            data = json.loads(body or "{}")
        except ValueError:
            raise ValidationError("the body must be JSON") from None
        if not isinstance(data, dict):
            raise ValidationError("the body must be a JSON object")
        return data
