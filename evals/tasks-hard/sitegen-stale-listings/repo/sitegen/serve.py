"""`sitegen serve`: serve public/ and rebuild whenever a source file changes."""

import functools
import hashlib
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sitegen.builder import Builder, BuildReport

WATCHED = ("site.toml", "content", "templates", "static")


def snapshot(root: Path) -> dict[str, str]:
    """A digest of every watched file, so any edit, addition or removal shows up."""
    files: dict[str, str] = {}
    for name in WATCHED:
        path = root / name
        candidates = [path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []
        for candidate in candidates:
            if candidate.is_file():
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
                files[candidate.relative_to(root).as_posix()] = digest
    return files


class Watcher:
    def __init__(self, builder: Builder) -> None:
        self.builder = builder
        self.last = snapshot(builder.root)

    def poll_once(self) -> BuildReport | None:
        """Rebuild if anything changed since the last poll; return the report, if any."""
        current = snapshot(self.builder.root)
        if current == self.last:
            return None
        self.last = current
        return self.builder.build()


def serve(root: Path, *, port: int = 8000, drafts: bool = False, interval: float = 0.5) -> None:
    builder = Builder(root, drafts=drafts)
    print(builder.build().describe())
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(builder.config.output_dir))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Serving on http://127.0.0.1:{port}/ (ctrl+c to stop)")
    watcher = Watcher(builder)
    try:
        while True:
            time.sleep(interval)
            try:
                report = watcher.poll_once()
            except Exception as exc:  # keep serving; the next save may fix it
                print(f"build failed: {exc}")
                continue
            if report is not None:
                print(report.describe())
                for path in report.written:
                    print(f"  + {path}")
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
