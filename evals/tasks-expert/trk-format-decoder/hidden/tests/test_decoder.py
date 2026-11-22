"""The decoder against the logger's real format: the samples, then fresh files written by
the encoder with every mix of version and export settings, then damaged files."""

import json
import math
import random
from pathlib import Path

import pytest
from trk_encoder import CHECKSUM, encode
from trk_random import random_log

from trkfile import TrkError, decode

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
NAMES = sorted(path.stem for path in SAMPLES.glob("*.trk"))
TOLERANCE = {"lat": 6e-7, "lon": 6e-7, "alt": 0.051, "seconds": 0.0051}


def assert_same_log(got: object, want: dict, about: str) -> None:
    assert isinstance(got, dict), about
    assert got.get("version") == want["version"], f"{about}: version"
    assert got.get("device") == want["device"], f"{about}: device"
    records = got.get("records")
    assert isinstance(records, list), about
    assert len(records) == len(want["records"]), f"{about}: number of records"
    for index, (mine, theirs) in enumerate(zip(records, want["records"], strict=True)):
        where = f"{about}: record {index} ({theirs['type']})"
        assert isinstance(mine, dict), where
        assert set(mine) == set(theirs), f"{where}: keys {sorted(mine)} != {sorted(theirs)}"
        for key, value in theirs.items():
            if key in TOLERANCE:
                assert isinstance(mine[key], int | float), f"{where}: {key}"
                assert math.isclose(mine[key], value, abs_tol=TOLERANCE[key]), (
                    f"{where}: {key} is {mine[key]!r}, the device recorded {value!r}"
                )
            else:
                assert mine[key] == value and type(mine[key]) is type(value), (
                    f"{where}: {key} is {mine[key]!r}, the device recorded {value!r}"
                )


@pytest.mark.parametrize("name", NAMES)
def test_every_sample_decodes_to_what_the_vendor_tool_shows(name: str) -> None:
    want = json.loads((SAMPLES / f"{name}.json").read_text("utf-8"))

    assert_same_log(decode((SAMPLES / f"{name}.trk").read_bytes()), want, name)


@pytest.mark.parametrize("name", ["cut-short", "left-over", "bad-checksum", "unknown-record"])
def test_the_files_the_vendor_tool_refuses_are_refused(name: str) -> None:
    with pytest.raises(TrkError):
        decode((SAMPLES / "bad" / f"{name}.trk").read_bytes())


@pytest.mark.parametrize("seed", range(300))
def test_a_fresh_file_decodes_to_what_was_recorded(seed: int) -> None:
    device, records, version, flags = random_log(random.Random(seed))
    data = encode(device, records, version, flags)

    got = decode(data)

    want = {"version": version, "device": device, "records": records}
    assert_same_log(got, want, f"seed {seed}, version {version}, flags {flags:#06b}")


@pytest.mark.parametrize("seed", range(60))
def test_a_file_cut_short_anywhere_is_refused(seed: int) -> None:
    rng = random.Random(1000 + seed)
    device, records, version, flags = random_log(rng)
    data = encode(device, records or [{"type": "battery", "t": 5, "percent": 50, "mv": 3700}], version, flags)
    cut = rng.choice([len(data) - 1, len(data) - 2, rng.randrange(6, len(data))])

    with pytest.raises(TrkError):
        decode(data[:cut])


@pytest.mark.parametrize("seed", range(40))
def test_bytes_after_the_last_record_are_refused(seed: int) -> None:
    rng = random.Random(2000 + seed)
    device, records, version, flags = random_log(rng)
    data = encode(device, records, version, flags)

    with pytest.raises(TrkError):
        decode(data + bytes(rng.choices([0, 0, 1, 255], k=rng.choice([1, 2, 3]))))


@pytest.mark.parametrize("seed", range(80))
def test_a_damaged_file_with_a_checksum_is_refused(seed: int) -> None:
    rng = random.Random(3000 + seed)
    device, records, version, flags = random_log(rng)
    data = bytearray(encode(device, records, version, flags | CHECKSUM))
    spot = rng.randrange(6, len(data))  # anywhere after the header, the checksum included
    data[spot] ^= rng.choice([1, 2, 4, 0x10, 0x80])

    with pytest.raises(TrkError):
        decode(bytes(data))


def test_a_checksum_is_checked_even_when_the_rest_reads_cleanly() -> None:
    records = [{"type": "note", "t": 100, "text": "abc"}]
    data = bytearray(encode("TR-200", records, 1, CHECKSUM))
    spot = bytes(data).index(b"abc")
    data[spot] = ord("x")  # still a well-formed file, but not the one the checksum is for

    with pytest.raises(TrkError):
        decode(bytes(data))


@pytest.mark.parametrize(
    ("version", "flags", "kind"), [(3, 0, 3), (0, 0, 3), (1, 16, 3), (2, 0x80, 3), (1, 0, 5), (2, 0, 0)]
)
def test_a_version_setting_or_record_nobody_has_seen_is_refused(
    version: int, flags: int, kind: int
) -> None:
    data = bytearray(encode("TR-200", [{"type": "battery", "t": 100, "percent": 50, "mv": 3700}], 2, 0))
    data[4], data[5] = version, flags
    data[6 + 1 + 6 + 1] = kind
    if version == 1:
        del data[-2:]  # version 1 batteries carry no millivolts

    with pytest.raises(TrkError):
        decode(bytes(data))
