import json
import re
from pathlib import Path
from typing import Any

from zwans.races import Race, project_of, save
from zwans.replay import LONGEST_PAUSE, RESULT_CHARS, build, filename, frames, scrub


def at(second: float, **event: Any) -> dict[str, Any]:
    whole, part = divmod(second, 1)
    stamp = f"2026-11-23T10:00:{int(whole):02d}.{int(part * 1000):03d}+00:00"
    return {"time": stamp, **event}


def test_secrets_are_masked_and_home_shortened() -> None:
    key = "sk-ant-" + "a1B2" * 8
    text = (
        f"ANTHROPIC_API_KEY={key}\n"
        'config: {"password": "hunter22hunter"}\n'
        "token ghp_" + "x" * 30 + "\n"
        "/Users/someone/project/app.py"
    )

    cleaned = scrub(text, home="/Users/someone")

    assert key not in cleaned and "hunter22hunter" not in cleaned and "ghp_x" not in cleaned
    assert cleaned.count("•••") == 3
    assert "~/project/app.py" in cleaned
    assert scrub("a plain sentence about keys", home=None) == "a plain sentence about keys"


def test_frames_keep_what_a_reader_follows_and_shorten_the_waits() -> None:
    events = [
        at(0, type="turn_started", prompt="Fix it", turn=1),
        at(0.5, type="thinking_delta", text="hmm"),
        at(1, type="text_delta", text="Look"),
        at(1.02, type="text_delta", text="ing."),
        at(1.1, type="model_call", dollars=0.25),
        at(1.2, type="tool_call_requested", call_id="c1", name="Bash", args={"command": "x"}),
        at(40, type="tool_result", call_id="c1", content="y" * (RESULT_CHARS + 10)),
        at(41, type="model_call", dollars=0.5),
        at(41, type="turn_ended", turn=1, stop_reason="end_turn"),
    ]

    played = frames(events)

    kinds = [f["type"] for f in played]
    shown = ["turn_started", "text_delta", "tool_call_requested", "tool_result", "turn_ended"]
    assert kinds == shown
    assert played[1]["text"] == "Looking."
    result = played[3]
    assert result["t"] - played[2]["t"] == LONGEST_PAUSE  # 38.8 s of a slow command, cut
    assert result["content"].endswith("… 10 more characters")
    assert played[-1]["dollars"] == 0.75 and played[-1]["total"] == 0.75
    assert all("time" not in f for f in played)


def test_the_page_carries_the_frames_and_nothing_can_close_its_script_early() -> None:
    events = [
        at(0, type="turn_started", prompt="Print </script><b>hi</b>", turn=1),
        at(1, type="turn_ended", turn=1, stop_reason="end_turn"),
    ]

    page = build(
        events, title="<Fix> the tests", model="m", workspace="/w/calc", created_at="2026-11-23"
    )

    assert "<title>&lt;Fix&gt; the tests · Zwans replay</title>" in page
    assert page.count("</script>") == 2  # the data block's own end and the player's
    found = re.search(r'id="data">(.*?)</script>', page, re.S)
    assert found is not None
    data = json.loads(found.group(1))
    assert data["meta"]["folder"] == "calc" and data["meta"]["turns"] == 1
    assert data["frames"][0]["prompt"] == "Print </script><b>hi</b>"
    assert filename("2026../x") == "zwans-replay-2026x.html"


def test_a_race_copy_is_named_by_its_project(tmp_path: Path) -> None:
    race = Race(id="r1", prompt="p", workspace="/work/calc", created_at="now")
    save(tmp_path, race)

    assert project_of(tmp_path, str(tmp_path / "races" / "r1" / "a")) == "/work/calc"
    assert project_of(tmp_path, "/work/other") == "/work/other"
