import json
from pathlib import Path

import pytest

from trkfile import TrkError, decode

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
READ_SO_FAR = ["01-morning-run", "02-trail-notes", "03-commute"]


@pytest.mark.parametrize("name", READ_SO_FAR)
def test_a_sample_decodes_to_what_the_vendor_tool_shows(name: str) -> None:
    want = json.loads((SAMPLES / f"{name}.json").read_text("utf-8"))

    assert decode((SAMPLES / f"{name}.trk").read_bytes()) == want


def test_something_that_isnt_a_trk_file_is_refused() -> None:
    with pytest.raises(TrkError):
        decode(b"GPX\x1a\x01\x00")
