"""Settings, looked up in this order:

1. environment variables: FETCHER_ plus the key upper-cased with dots as underscores
   (http.retries -> FETCHER_HTTP_RETRIES)
2. the config file named by FETCHER_CONFIG, if it is set (one `key = value` per line)
3. the profile's values (profile from FETCHER_PROFILE, default "standard")
4. DEFAULTS
"""

import os
from pathlib import Path

DEFAULTS = {
    "http.timeout": "120s",  # deadline for a whole download, retries included
    "http.attempt_timeout": "5s",
    "http.connect_timeout": "3s",
    "http.retries": "3",
    "http.backoff": "500ms",
    "http.user_agent": "fetcher/1.4",
    "cache.dir": ".fetch-cache",
    "cache.max_age": "1h",
}

PROFILES = {
    "standard": {"http.attempt_timeout": "1500ms", "http.retries": "4"},
    "patient": {"http.attempt_timeout": "30s", "http.timeout": "10m", "http.retries": "8"},
    "offline": {"http.retries": "0"},
}

UNITS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}


def parse_duration(text: str) -> float:
    """"1500ms" -> 1.5, "2m" -> 120.0, a bare number means seconds."""
    text = text.strip()
    for suffix in sorted(UNITS, key=len, reverse=True):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * UNITS[suffix]
    return float(text)


def read_file(path: str) -> dict[str, str]:
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


class Settings:
    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self.environ = dict(os.environ if environ is None else environ)
        profile = self.environ.get("FETCHER_PROFILE", "standard")
        self.values = {**DEFAULTS, **PROFILES[profile]}
        if "FETCHER_CONFIG" in self.environ:
            self.values.update(read_file(self.environ["FETCHER_CONFIG"]))

    def get(self, key: str) -> str:
        env_name = "FETCHER_" + key.upper().replace(".", "_")
        return self.environ.get(env_name, self.values[key])

    def seconds(self, key: str) -> float:
        return parse_duration(self.get(key))

    def integer(self, key: str) -> int:
        return int(self.get(key))
