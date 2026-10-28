"""Read the app's INI-style settings files.

    # comments start with # or ;
    [server]
    host = example.org
    port = 8080
    banner = "  Welcome!  "    (quotes keep surrounding spaces)

Section and key names are case-insensitive and stored in lower case.
"""

from pathlib import Path


class SettingsError(Exception):
    pass


Settings = dict[str, dict[str, str]]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(text: str) -> Settings:
    sections: Settings = {}
    current: dict[str, str] | None = None
    for number, line in enumerate(text.split("\n"), start=1):
        if not line or line.isspace() or line.lstrip()[0] in "#;":
            continue
        if line[0] == "[":
            if line[-1] != "]":
                raise SettingsError(f"line {number}: unclosed section header")
            name = line[1:-1].strip().lower()
            if not name:
                raise SettingsError(f"line {number}: empty section name")
            current = sections.setdefault(name, {})
            continue
        key, sep, value = line.partition("=")
        if not sep or not key.strip():
            raise SettingsError(f"line {number}: expected key = value")
        if current is None:
            raise SettingsError(f"line {number}: setting outside of a section")
        current[key.strip().lower()] = _unquote(value.strip())
    return sections


def parse_bytes(data: bytes) -> Settings:
    """Parse settings from raw bytes, e.g. an uploaded file. Settings files are UTF-8."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SettingsError(f"not valid UTF-8: {exc}") from exc
    return parse(text)


def load(path: str | Path) -> Settings:
    return parse_bytes(Path(path).read_bytes())
