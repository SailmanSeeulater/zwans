from pathlib import Path

import pytest

from appconfig import SettingsError, load, parse, parse_bytes
from appconfig.access import get_bool, get_int, get_str

LINES = [
    "# shop settings",
    "[Server]",
    "host = example.org",
    "port = 8080",
    "",
    "[display]",
    'banner = "  Grüß Gott!  "',
    "dark_mode = no",
]
EXPECTED = {
    "server": {"host": "example.org", "port": "8080"},
    "display": {"banner": "  Grüß Gott!  ", "dark_mode": "no"},
}
BOM = b"\xef\xbb\xbf"


def crlf_bytes() -> bytes:
    return ("\r\n".join(LINES) + "\r\n").encode("utf-8")


def test_crlf_text() -> None:
    assert parse("\r\n".join(LINES) + "\r\n") == EXPECTED


def test_crlf_bytes() -> None:
    assert parse_bytes(crlf_bytes()) == EXPECTED


def test_bom_with_lf() -> None:
    data = BOM + ("\n".join(LINES) + "\n").encode("utf-8")

    assert parse_bytes(data) == EXPECTED


def test_bom_with_crlf_from_file(tmp_path: Path) -> None:
    path = tmp_path / "notepad.ini"
    path.write_bytes(BOM + crlf_bytes())

    settings = load(path)

    assert settings == EXPECTED
    assert get_int(settings, "server", "port") == 8080
    assert get_bool(settings, "display", "dark_mode") is False
    assert get_str(settings, "display", "banner") == "  Grüß Gott!  "


def test_bom_directly_before_a_comment() -> None:
    data = BOM + b"; settings\r\n[a]\r\nx = 1\r\n"

    assert parse_bytes(data) == {"a": {"x": "1"}}


def test_crlf_without_final_newline() -> None:
    assert parse("[a]\r\nx = 1\r\ny = 2") == {"a": {"x": "1", "y": "2"}}


def test_crlf_errors_keep_line_numbers() -> None:
    with pytest.raises(SettingsError, match="line 3: expected key = value"):
        parse_bytes(b"[a]\r\nx = 1\r\nnonsense\r\n")


def test_not_utf8() -> None:
    with pytest.raises(SettingsError):
        parse_bytes(b"[a]\r\nname = \xff\xfe\r\n")
