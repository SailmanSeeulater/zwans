"""What the last build wrote, so the next build can skip outputs that haven't changed."""

import json
from pathlib import Path

from sitegen import __version__

CACHE_NAME = ".sitegen-cache.json"
FORMAT = 2


class BuildCache:
    def __init__(self, path: Path, outputs: dict[str, str] | None = None) -> None:
        self.path = path
        self.outputs: dict[str, str] = dict(outputs or {})

    @classmethod
    def load(cls, output_dir: Path) -> "BuildCache":
        path = output_dir / CACHE_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path)
        # A cache from another version of sitegen may mean something else; start over.
        if data.get("format") != FORMAT or data.get("sitegen") != __version__:
            return cls(path)
        outputs = data.get("outputs")
        if not isinstance(outputs, dict):
            return cls(path)
        return cls(path, {str(k): str(v) for k, v in outputs.items()})

    def is_fresh(self, output: str, signature: str) -> bool:
        return self.outputs.get(output) == signature

    def record(self, output: str, signature: str) -> None:
        self.outputs[output] = signature

    def forget(self, output: str) -> None:
        self.outputs.pop(output, None)

    def paths(self) -> set[str]:
        return set(self.outputs)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "format": FORMAT,
            "sitegen": __version__,
            "outputs": dict(sorted(self.outputs.items())),
        }
        self.path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
