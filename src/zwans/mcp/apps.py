"""MCP Apps: a tool's result shown as an interactive view in the web UI.

A tool that has a view names it in its definition, as `_meta.ui.resourceUri`, a `ui://`
resource on the same server. After such a call, Zwans reads that resource (HTML, with what
it may load in `_meta.ui.csp`) and sends it with the tool's result in the tool_result event.
The web UI shows it in a sandboxed iframe and talks to it over postMessage
(web/src/lib/apps.ts). Calls the view makes back to its server reach the session through
the server's API and go through the same policy as the model's (LiveSession.app_call).

The spec: https://github.com/modelcontextprotocol/ext-apps (2026-01-26).
"""

import base64
import binascii
from typing import Any

from zwans.mcp.client import APP_MIME_TYPE, Connection, McpError

UI_SCHEME = "ui://"
MAX_HTML_BYTES = 2 * 1024 * 1024  # a bigger view isn't shown; the text result still is
CSP_KEYS = ("connectDomains", "resourceDomains", "frameDomains", "baseUriDomains")
PERMISSION_KEYS = ("camera", "microphone", "geolocation", "clipboardWrite")


def ui_meta(spec: dict[str, Any]) -> dict[str, Any]:
    meta = spec.get("_meta")
    ui = meta.get("ui") if isinstance(meta, dict) else None
    return ui if isinstance(ui, dict) else {}


def resource_uri(spec: dict[str, Any]) -> str | None:
    """The view a tool's results are shown in, if it has one. Early servers used the flat
    `_meta["ui/resourceUri"]`, which the spec keeps until GA."""
    uri = ui_meta(spec).get("resourceUri")
    if uri is None:
        meta = spec.get("_meta")
        uri = meta.get("ui/resourceUri") if isinstance(meta, dict) else None
    return uri if isinstance(uri, str) and uri.startswith(UI_SCHEME) else None


def visibility(spec: dict[str, Any]) -> frozenset[str]:
    """Who may call the tool: "model", "app" (its views), or both, the default."""
    seen = ui_meta(spec).get("visibility")
    if not isinstance(seen, list):
        return frozenset({"model", "app"})
    return frozenset(item for item in seen if item in ("model", "app"))


class ViewCache:
    """A server's views, read once each: a view is the same page for every call."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._views: dict[str, dict[str, Any] | None] = {}

    async def get(self, uri: str) -> dict[str, Any] | None:
        if uri not in self._views:
            self._views[uri] = await self._read(uri)
        return self._views[uri]

    async def _read(self, uri: str) -> dict[str, Any] | None:
        """The view at `uri`, or None for one that can't be read or isn't an app's HTML.
        A missing view leaves the plain result, so it isn't an error for the model."""
        try:
            result = await self.connection.read_resource(uri)
        except McpError:
            return None
        return view_from(uri, result)


def view_from(uri: str, result: dict[str, Any]) -> dict[str, Any] | None:
    contents = result.get("contents")
    if not isinstance(contents, list):
        return None
    for item in contents:
        if not isinstance(item, dict) or item.get("uri", uri) != uri:
            continue
        mime = str(item.get("mimeType") or "").replace(" ", "").lower()
        if mime != APP_MIME_TYPE:
            continue
        html = _html(item)
        if html is None or len(html.encode("utf-8")) > MAX_HTML_BYTES:
            return None
        ui = ui_meta(item)
        csp = _object(ui.get("csp"))
        permissions = _object(ui.get("permissions"))
        border = ui.get("prefersBorder")
        return {
            "uri": uri,
            "html": html,
            "csp": {key: _strings(csp.get(key)) for key in CSP_KEYS if csp.get(key)},
            "permissions": [key for key in PERMISSION_KEYS if key in permissions],
            "prefers_border": border if isinstance(border, bool) else None,
        }
    return None


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _html(item: dict[str, Any]) -> str | None:
    if isinstance(item.get("text"), str):
        return str(item["text"])
    if isinstance(item.get("blob"), str):
        try:
            return base64.b64decode(item["blob"], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    return None


def _strings(value: Any) -> list[str]:
    """Origins a view may reach. Anything that could close the CSP directive and start
    another (a space, a semicolon, a quote) is dropped rather than trusted."""
    if not isinstance(value, list):
        return []
    return [
        item
        for item in value
        if isinstance(item, str) and item and not any(c in item for c in " ;,'\"\n\t")
    ]


def tool_info(spec: dict[str, Any]) -> dict[str, Any]:
    """The tool as the view is told about it (hostContext.toolInfo.tool)."""
    keys = ("name", "title", "description", "inputSchema", "annotations", "_meta")
    return {key: spec[key] for key in keys if key in spec}


def app_result(result: dict[str, Any]) -> dict[str, Any]:
    """The parts of a CallToolResult a view is sent (ui/notifications/tool-result)."""
    keys = ("content", "structuredContent", "isError", "_meta")
    return {key: result[key] for key in keys if key in result}
