"""A tiny MCP server over stdio, for the client's tests. Its tools:

- echo: returns its text. Marked read-only.
- fail: returns an error result.
- slow: sleeps for `seconds` before answering.
- ping_me: pings the client first, and reports whether the client answered.
- quit: exits without answering.
- env: returns the value of the environment variable `name`.
- chart: returns numbers, with a view of them (MCP Apps) at ui://fake/chart.html.
- shuffle: only views may call it (visibility ["app"]); returns the numbers reversed.
- secret: only the model may call it (visibility ["model"]).
- client: returns how many views were read and the capabilities the client sent.

tools/list comes in two pages, to exercise the cursor.
"""

import json
import os
import sys
import threading
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Return the text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {"name": "fail", "inputSchema": {"type": "object"}},
    {"name": "slow", "inputSchema": {"type": "object"}},
    {"name": "ping_me", "inputSchema": {"type": "object"}},
    {"name": "quit", "inputSchema": {"type": "object"}},
    {"name": "env", "inputSchema": {"type": "object"}},
    {
        "name": "chart",
        "description": "Chart the numbers.",
        "inputSchema": {"type": "object"},
        "_meta": {"ui": {"resourceUri": "ui://fake/chart.html"}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "shuffle",
        "inputSchema": {"type": "object"},
        "_meta": {"ui": {"resourceUri": "ui://fake/chart.html", "visibility": ["app"]}},
    },
    {
        "name": "secret",
        "inputSchema": {"type": "object"},
        "_meta": {"ui": {"visibility": ["model"]}},
    },
    {"name": "client", "inputSchema": {"type": "object"}},
]
VIEW = "<!doctype html><title>Chart</title><script>/* draws the numbers */</script>"
VIEW_META = {
    "ui": {
        "csp": {"resourceDomains": ["https://cdn.example.com", "bad; script-src *"]},
        "permissions": {"clipboardWrite": {}},
        "prefersBorder": False,
    }
}
state: dict[str, object] = {"reads": 0, "capabilities": None}

lock = threading.Lock()
replies: dict[object, dict[str, object]] = {}
arrived = threading.Condition(lock)


def send(message: dict[str, object]) -> None:
    with lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


def text(request_id: object, value: str, is_error: bool = False) -> None:
    result = {"content": [{"type": "text", "text": value}], "isError": is_error}
    send({"jsonrpc": "2.0", "id": request_id, "result": result})


def call(request_id: object, name: str, args: dict[str, object]) -> None:
    if name == "echo":
        text(request_id, str(args["text"]))
    elif name == "fail":
        text(request_id, "That didn't work.", is_error=True)
    elif name == "slow":
        time.sleep(float(str(args.get("seconds", 5))))
        text(request_id, "finally")
    elif name == "ping_me":
        send({"jsonrpc": "2.0", "id": "server-ping", "method": "ping"})
        with arrived:
            arrived.wait_for(lambda: "server-ping" in replies, timeout=5)
            answered = replies.get("server-ping", {})
        text(request_id, f"client answered: {json.dumps(answered.get('result'))}")
    elif name == "quit":
        os._exit(3)
    elif name == "env":
        text(request_id, os.environ.get(str(args["name"]), "(unset)"))
    elif name in ("chart", "shuffle"):
        numbers = [int(n) for n in args.get("numbers", [3, 1, 2])]  # type: ignore[attr-defined]
        if name == "shuffle":
            numbers.reverse()
        result = {
            "content": [{"type": "text", "text": f"numbers: {numbers}"}],
            "structuredContent": {"numbers": numbers},
        }
        send({"jsonrpc": "2.0", "id": request_id, "result": result})
    elif name == "secret":
        text(request_id, "only for the model")
    elif name == "client":
        text(request_id, json.dumps(state))


def main() -> None:
    print("a stray line that isn't JSON", flush=True)
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get("method")
        request_id = message.get("id")
        if method is None:  # a reply to our ping
            with arrived:
                replies[request_id] = message
                arrived.notify_all()
        elif method == "initialize":
            state["capabilities"] = message["params"].get("capabilities")
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1"},
                "instructions": "  Use echo to repeat text back.\n",
            }
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        elif method == "tools/list":
            page: dict[str, object] = {"tools": TOOLS[3:]}
            if message["params"].get("cursor") != "page2":
                page = {"tools": TOOLS[:3], "nextCursor": "page2"}
            send({"jsonrpc": "2.0", "id": request_id, "result": page})
        elif method == "tools/call":
            params = message["params"]
            args = (request_id, params["name"], params.get("arguments", {}))
            threading.Thread(target=call, args=args, daemon=True).start()
        elif method == "resources/read" and message["params"]["uri"] == "ui://fake/chart.html":
            state["reads"] = int(str(state["reads"])) + 1
            view = {
                "uri": "ui://fake/chart.html",
                "mimeType": "text/html;profile=mcp-app",
                "text": VIEW,
                "_meta": VIEW_META,
            }
            send({"jsonrpc": "2.0", "id": request_id, "result": {"contents": [view]}})
        elif request_id is not None:
            error = {"code": -32601, "message": f"no method {method}"}
            send({"jsonrpc": "2.0", "id": request_id, "error": error})


if __name__ == "__main__":
    main()
