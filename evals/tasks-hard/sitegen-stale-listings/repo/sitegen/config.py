"""Site settings, read from site.toml in the site's root folder."""

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    root: Path
    title: str = "Untitled site"
    base_url: str = "http://localhost:8000/"
    author: str = ""
    language: str = "en"
    posts_per_page: int = 5
    feed_size: int = 10
    date_format: str = "%d %b %Y"
    excerpt_words: int = 60

    @property
    def content_dir(self) -> Path:
        return self.root / "content"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    @property
    def static_dir(self) -> Path:
        return self.root / "static"

    @property
    def output_dir(self) -> Path:
        return self.root / "public"

    def absolute_url(self, url: str) -> str:
        return self.base_url.rstrip("/") + "/" + url.lstrip("/")

    def fingerprint(self) -> str:
        """Changes whenever a setting that shows up on pages changes."""
        settings = asdict(self)
        del settings["root"]
        text = json.dumps(settings, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


_INT_SETTINGS = ("posts_per_page", "feed_size", "excerpt_words")
_STR_SETTINGS = ("title", "base_url", "author", "language", "date_format")


def load_config(root: Path) -> Config:
    root = Path(root)
    path = root / "site.toml"
    if not path.is_file():
        raise ConfigError(f"{root} has no site.toml; is it a sitegen site?")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"site.toml: {exc}") from exc

    settings: dict[str, object] = {}
    for key, value in data.items():
        if key in _INT_SETTINGS:
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ConfigError(f"site.toml: {key} must be a whole number of at least 1")
        elif key in _STR_SETTINGS:
            if not isinstance(value, str):
                raise ConfigError(f"site.toml: {key} must be text")
        else:
            raise ConfigError(f"site.toml: unknown setting {key!r}")
        settings[key] = value
    base_url = settings.get("base_url")
    if isinstance(base_url, str) and not base_url.endswith("/"):
        settings["base_url"] = base_url + "/"
    return Config(root=root, **settings)  # type: ignore[arg-type]
