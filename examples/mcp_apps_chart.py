"""A small MCP server with an MCP Apps view: a bar chart of the numbers the model gives it.

Plain Python, no packages, over stdio. To try it, add it to ~/.zwans/config.toml:

    [mcp_servers.chart]
    command = "python3"
    args = ["/path/to/zwans/examples/mcp_apps_chart.py"]

and ask for a chart in the web UI ("Chart our signups: Mon 12, Tue 19, Wed 7"). Its tools:

- chart: the model's. Shows the numbers as bars in the view at ui://chart/bar.html.
- regenerate: only the view's (visibility ["app"]). The view's "New numbers" button calls it;
  it doesn't claim to be read-only, so Zwans asks before it runs in ask mode.

The view's "Ask about this" button puts a question about the chart in the composer.
"""

from __future__ import annotations  # runs on older Pythons than Zwans needs

import json
import random
import sys
from typing import Any

VIEW_URI = "ui://chart/bar.html"
MIME = "text/html;profile=mcp-app"

TOOLS = [
    {
        "name": "chart",
        "title": "Bar chart",
        "description": "Show numbers as a bar chart the user can see and interact with.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "values": {"type": "array", "items": {"type": "number"}},
            },
            "required": ["labels", "values"],
        },
        "annotations": {"readOnlyHint": True},
        "_meta": {"ui": {"resourceUri": VIEW_URI}},
    },
    {
        "name": "regenerate",
        "description": "New random numbers for the same labels.",
        "inputSchema": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "labels": {"type": "array"}},
        },
        "_meta": {"ui": {"resourceUri": VIEW_URI, "visibility": ["app"]}},
    },
]

# The view talks JSON-RPC over postMessage by hand, to show the whole protocol; a real one
# would more likely use the App class from @modelcontextprotocol/ext-apps.
VIEW = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0; padding: 14px 16px;
    font: var(--font-text-sm-size, 13px)/1.4 var(--font-sans, system-ui, sans-serif);
    color: var(--color-text-primary, CanvasText);
  }
  h1 { font-size: var(--font-heading-xs-size, 13px); margin: 0 0 10px; font-weight: 600; }
  .bars { display: grid; gap: 6px; }
  .row { display: grid; grid-template-columns: 7em 1fr 3.5em; align-items: center; gap: 8px; }
  .label { color: var(--color-text-secondary, GrayText);
           overflow: hidden; text-overflow: ellipsis; }
  .track { height: 16px; border-radius: var(--border-radius-sm, 6px);
           background: var(--color-background-tertiary, rgba(127,127,127,.12)); }
  .bar { height: 100%; border-radius: inherit; background: var(--color-ring-primary, #0b63ce);
         transition: width 300ms ease-out; }
  .value { text-align: right; font-family: var(--font-mono, monospace);
           font-size: var(--font-text-xs-size, 11px); }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  button {
    font: inherit; padding: 4px 10px; cursor: pointer;
    border-radius: var(--border-radius-md, 8px);
    border: 1px solid var(--color-border-primary, rgba(127,127,127,.4));
    background: var(--color-background-secondary, transparent);
    color: var(--color-text-primary, CanvasText);
  }
  .status { color: var(--color-text-secondary, GrayText); align-self: center; }
</style>
</head>
<body>
<h1 id="title">Waiting for the numbers…</h1>
<div class="bars" id="bars"></div>
<div class="actions">
  <button id="regenerate">New numbers</button>
  <button id="ask">Ask about this</button>
  <span class="status" id="status"></span>
</div>
<script>
  let nextId = 1;
  const waiting = new Map();
  let data = { title: "", labels: [], values: [] };

  function send(message) { window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*"); }
  function request(method, params) {
    const id = nextId++;
    send({ id, method, params });
    return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
  }

  function applyContext(context) {
    if (!context) return;
    if (context.theme) document.documentElement.style.colorScheme = context.theme;
    const variables = (context.styles && context.styles.variables) || {};
    for (const [name, value] of Object.entries(variables)) {
      if (value) document.documentElement.style.setProperty(name, value);
    }
  }

  function draw(next) {
    data = next;
    document.getElementById("title").textContent = data.title || "Chart";
    const max = Math.max(1, ...data.values);
    const bars = document.getElementById("bars");
    bars.replaceChildren(...data.labels.map((label, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="label"></span>' +
        '<div class="track"><div class="bar"></div></div><span class="value"></span>';
      row.querySelector(".label").textContent = label;
      row.querySelector(".bar").style.width = (100 * (data.values[i] || 0) / max) + "%";
      row.querySelector(".value").textContent = data.values[i];
      return row;
    }));
  }

  function fromResult(result) {
    if (result && result.structuredContent) draw(result.structuredContent);
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data || {};
    if (message.id !== undefined && !message.method) {
      const pending = waiting.get(message.id);
      waiting.delete(message.id);
      if (!pending) return;
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    } else if (message.method === "ui/notifications/tool-result") {
      fromResult(message.params);
    } else if (message.method === "ui/notifications/host-context-changed") {
      applyContext(message.params);
    } else if (message.method === "ui/resource-teardown") {
      send({ id: message.id, result: {} });
    }
  });

  const status = (text) => { document.getElementById("status").textContent = text; };
  document.getElementById("regenerate").onclick = async () => {
    status("Asking…");
    try {
      const args = { title: data.title, labels: data.labels };
      const result = await request("tools/call", { name: "regenerate", arguments: args });
      if (result.isError) status(result.content[0].text); else { fromResult(result); status(""); }
    } catch (error) { status(error.message); }
  };
  document.getElementById("ask").onclick = () => {
    const pairs = data.labels.map((label, i) => label + " " + data.values[i]).join(", ");
    const text = "What stands out in " + (data.title || "this chart") + " (" + pairs + ")?";
    request("ui/message", { role: "user", content: [{ type: "text", text }] })
      .catch((error) => status(error.message));
  };

  new ResizeObserver(() => {
    const height = document.documentElement.scrollHeight;
    send({ method: "ui/notifications/size-changed", params: { height } });
  }).observe(document.body);

  request("ui/initialize", {
    appInfo: { name: "chart", version: "1.0.0" },
    appCapabilities: {},
    protocolVersion: "2026-01-26",
  }).then((result) => {
    applyContext(result.hostContext);
    send({ method: "ui/notifications/initialized" });
  });
</script>
</body>
</html>
"""


def result(title: str, labels: list[str], values: list[float]) -> dict[str, Any]:
    shown = [f"{label}: {values[i]:g}" for i, label in enumerate(labels) if i < len(values)]
    pairs = ", ".join(shown)
    return {
        "content": [{"type": "text", "text": f"Charted {title or 'the numbers'}: {pairs}"}],
        "structuredContent": {"title": title, "labels": labels, "values": values},
    }


def answer(message: dict[str, Any]) -> dict[str, Any] | None:
    method, params = message.get("method"), message.get("params") or {}
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "chart", "version": "1.0.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "resources/list":
        return {"resources": [{"uri": VIEW_URI, "name": "Bar chart", "mimeType": MIME}]}
    if method == "resources/read" and params.get("uri") == VIEW_URI:
        view = {"uri": VIEW_URI, "mimeType": MIME, "text": VIEW, "_meta": {"ui": {}}}
        return {"contents": [view]}
    if method == "tools/call":
        args = params.get("arguments") or {}
        labels = [str(label) for label in args.get("labels") or []]
        if params.get("name") == "chart":
            values = [float(v) for v in args.get("values") or []]
            return result(str(args.get("title") or ""), labels, values)
        if params.get("name") == "regenerate":
            values = [float(random.randint(1, 30)) for _ in labels]
            return result(str(args.get("title") or ""), labels, values)
    if method == "ping":
        return {}
    return None


def main() -> None:
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message or "method" not in message:
            continue  # notifications, and replies to requests this server never sends
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        found = answer(message)
        if found is None:
            reply["error"] = {"code": -32601, "message": f"no method {message['method']}"}
        else:
            reply["result"] = found
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
