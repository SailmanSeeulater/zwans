from pathlib import Path

import pytest

from appconfig import SettingsError, load, parse
from appconfig.access import get_bool, get_int, get_str

SAMPLE = """# shop settings
[Server]
host = example.org
Port = 8080

; display
[display]
banner = "  Welcome!  "
dark_mode = yes
"""


def test_parse_sections_and_keys() -> None:
    settings = parse(SAMPLE)

    assert settings == {
        "server": {"host": "example.org", "port": "8080"},
        "display": {"banner": "  Welcome!  ", "dark_mode": "yes"},
    }


def test_typed_access() -> None:
    settings = parse(SAMPLE)

    assert get_int(settings, "server", "port") == 8080
    assert get_bool(settings, "display", "dark_mode") is True
    assert get_str(settings, "server", "user", default="admin") == "admin"


def test_load_from_file(tmp_path: Path) -> None:
    path = tmp_path / "app.ini"
    path.write_bytes(SAMPLE.encode("utf-8"))

    assert get_str(load(path), "server", "host") == "example.org"


def test_setting_outside_a_section() -> None:
    with pytest.raises(SettingsError, match="line 1"):
        parse("host = x\n")


def test_unclosed_header() -> None:
    with pytest.raises(SettingsError, match="line 2: unclosed"):
        parse("# hi\n[server\n")
