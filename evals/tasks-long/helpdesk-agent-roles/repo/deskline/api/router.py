"""The JSON API: one request in, one response out.

A request is ``{"action": "tickets.get", "agent": "maria", "params": {"id": "T-1"}}``.
The response is ``{"ok": true, "data": ...}`` or
``{"ok": false, "error": {"code": "not_found", "message": "..."}}``.
"""

from __future__ import annotations

import json
from typing import Any

from ..desk import Desk
from ..errors import DesklineError, ValidationError
from .handlers import ACTIONS
from .params import Params


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def dispatch(desk: Desk, request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        return _error("invalid", "a request must be an object")
    name = request.get("action")
    handler = ACTIONS.get(name) if isinstance(name, str) else None
    if handler is None:
        return _error("unknown_action", f"no action {name!r}")
    agent = request.get("agent")
    if agent is not None and not isinstance(agent, str):
        return _error("invalid", "agent must be a string")
    try:
        ctx = desk.context(agent)
        params = Params(request.get("params"))
        data = handler(ctx, params)
    except ValidationError as exc:
        return _error("invalid", exc.message)
    except DesklineError as exc:
        return _error(exc.code, exc.message)
    return {"ok": True, "data": data}


def handle_json(desk: Desk, text: str) -> str:
    try:
        request = json.loads(text)
    except json.JSONDecodeError as exc:
        return json.dumps(_error("invalid", f"bad JSON: {exc}"))
    return json.dumps(dispatch(desk, request), sort_keys=True)


def actions() -> list[str]:
    return sorted(ACTIONS)
