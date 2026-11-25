import re

import pytest

import logq
from logq.cli import main


def test_the_readme_examples() -> None:
    pattern = logq.compile(r"(\d+\.){3}\d+")

    assert pattern.search("from 10.0.0.12 port 22") == (5, 14)
    assert pattern.fullmatch("10.0.0.12")
    assert logq.compile("a|ab").search("ab") == (0, 1)
    assert logq.compile("(a|ab)(c|bcd)").search("abcd") == (0, 4)
    assert logq.compile("(ab|c){2,3}d").size == 10


@pytest.mark.parametrize(
    ("pattern", "text"),
    [
        ("user=\\w+ (login|logout)", "10:22 user=ana login"),
        ("[^ ]+$", "a b ccc"),
        ("^a{2,3}", "aaaa"),
        ("x[a-c-]*y", "zzx-ab-cyy"),
        ("(a|b)*b", "aabab"),
        ("colou?r", "the color"),
        ("\\[[^\\]]*\\]", "level [warn] disk"),
        ("a{0}b", "ab"),
        ("q|", "abc"),
        ("(ab)+$", "xabab"),
        ("\\d{2,}", "a1b22c333"),
    ],
)
def test_matches_like_re(pattern: str, text: str) -> None:
    compiled = logq.compile(pattern)
    expected = re.search(pattern, text)

    assert compiled.search(text) == (expected.span() if expected else None)
    assert compiled.fullmatch(text) == (re.fullmatch(pattern, text) is not None)


@pytest.mark.parametrize(
    "pattern",
    ["*a", "a**", "a+?", "(a?)*", "(a|)+", "()*", "[]", "[z-a]", "a{3,2}", "\\n", "(ab", "ab)",
     "a]", "a{2"],
)
def test_bad_patterns(pattern: str) -> None:
    with pytest.raises(logq.PatternError):
        logq.compile(pattern)


def test_a_meter_counts_steps_and_can_stop_a_match() -> None:
    meter = logq.Meter()
    logq.compile("ab").search("xab", meter)
    assert meter.steps > 0

    with pytest.raises(logq.StepLimitExceeded):
        logq.compile("b").search("aaaaaaaa", logq.Meter(limit=3))


def test_the_command_line(tmp_path, capsys) -> None:
    log = tmp_path / "app.log"
    log.write_text("10:22 user=ana login\n10:25 disk full\n10:31 user=bo logout\n")

    assert main(["user=\\w+", str(log)]) == 0
    assert capsys.readouterr().out == "10:22 user=ana login\n10:31 user=bo logout\n"

    assert main(["user=\\w+", str(log), "-o"]) == 0
    assert capsys.readouterr().out == "user=ana\nuser=bo\n"

    assert main(["disk", str(log), "-c"]) == 0
    assert capsys.readouterr().out == "1\n"

    assert main(["nothing", str(log)]) == 1
    assert main(["(", str(log)]) == 2
