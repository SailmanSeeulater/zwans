"""`zwans serve`: the server behind the web UI and `zwans attach`."""

import contextlib
import json
import os
import secrets
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn

from zwans.config import load_settings
from zwans.server.app import ServerSettings, create_app

DEFAULT_PORT = 8765
WS_MAX_BYTES = 32 * 1024 * 1024  # five images of 3.75 MB, base64-encoded, and some room
# The UI built in this checkout (web/out), when Zwans is installed from it with pip -e.
CHECKOUT_UI = Path(__file__).resolve().parents[3] / "web" / "out"
# The UI inside the package, when Zwans is installed from a wheel (see hatch_build.py).
PACKAGED_UI = Path(__file__).resolve().parents[1] / "web"
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def default_ui() -> Path:
    return PACKAGED_UI if (PACKAGED_UI / "index.html").is_file() else CHECKOUT_UI


def server_file(home: Path) -> Path:
    """Where a running server leaves its address and token, for `zwans attach`."""
    return home / "server.json"


def read_server_file(home: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(server_file(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "url" in data and "token" in data else None


def serve(
    port: Annotated[int, typer.Option(help="Port to listen on.")] = DEFAULT_PORT,
    host: Annotated[
        str, typer.Option(help="Address to listen on. Keep it local: the server runs commands.")
    ] = "127.0.0.1",
    reports: Annotated[Path, typer.Option(help="Folder of eval reports for the dashboard.")] = Path(
        "evals/reports"
    ),
    web: Annotated[
        Path | None,
        typer.Option(help="The built web UI. Default: the one installed with Zwans, or web/out."),
    ] = None,
    dev_origin: Annotated[
        str | None,
        typer.Option(help="Let a `next dev` server at this origin call the API.", hidden=True),
    ] = None,
) -> None:
    """Start the server for the web UI and `zwans attach`, on this machine only."""
    config, env = load_settings()
    if host not in LOOPBACK:
        typer.secho(
            f"Listening on {host}: anyone who can reach it and has the token can run "
            "commands on this machine.",
            fg="yellow",
        )
    token = secrets.token_urlsafe(24)
    settings = ServerSettings(
        config=config,
        env=env,
        token=token,
        reports=reports.resolve(),
        web_dir=(web or default_ui()).resolve(),
        dev_origin=dev_origin,
    )
    app = create_app(settings)
    shown = "localhost" if host in LOOPBACK else host
    url = f"http://{shown}:{port}"
    path = server_file(config.home)
    _write_private(path, json.dumps({"url": url, "token": token, "pid": os.getpid()}))
    # The token goes after #, which browsers never send to the server.
    typer.echo(f"Zwans server: {url}/#token={token}")
    typer.secho("Ctrl+C stops it, and every session it's running.", dim=True)
    try:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="warning",
            ws_max_size=WS_MAX_BYTES,  # a prompt can carry several images
        )
    finally:
        current = read_server_file(config.home)
        if current is not None and current.get("pid") == os.getpid():
            with contextlib.suppress(OSError):
                path.unlink()


def _write_private(path: Path, text: str) -> None:
    """Write a file only its owner can read: it holds the token."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
