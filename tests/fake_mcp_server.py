"""A tiny MCP server over stdio, for the client's tests. Its tools:

- echo: returns its text. Marked read-only.
- fail: returns an error result.
- slow: sleeps for `seconds` before answering.
- ping_me: pings the client first, and reports whether the client answered.
- quit: exits without answering.
- env: returns the value of the environment variable `name`.

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
]

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
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "1"},
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
        elif request_id is not None:
            error = {"code": -32601, "message": f"no method {method}"}
            send({"jsonrpc": "2.0", "id": request_id, "error": error})


if __name__ == "__main__":
    main()
