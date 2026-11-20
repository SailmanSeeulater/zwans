from zwans.cli.terminal_text import printable


def test_cursor_and_erase_codes_are_shown_as_text() -> None:
    assert printable("rm -rf ~\x1b[2K\x1b[1Gls") == "rm -rf ~\\x1b[2K\\x1b[1Gls"
    assert printable("evil\rgood") == "evil\\x0dgood"


def test_colour_codes_are_dropped_so_nothing_can_be_concealed() -> None:
    assert printable("\x1b[8mhidden\x1b[0m \x1b[1;31mred\x1b[m") == "hidden red"


def test_bidirectional_overrides_are_shown_as_text() -> None:
    assert printable("report‮gpj.exe") == "report\\u202egpj.exe"


def test_ordinary_text_is_left_alone() -> None:
    text = "def f():\n\treturn 'héllo · ✓'\r\n"
    assert printable(text) == "def f():\n\treturn 'héllo · ✓'\n"
