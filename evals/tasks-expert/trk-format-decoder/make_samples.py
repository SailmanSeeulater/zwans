"""Makes the trk-format-decoder task's samples from its hidden encoder. Run once; the files
are committed: repo/samples, with a copy in hidden/samples. usage: python make_samples.py"""

import json
import random
import sys
from pathlib import Path

task = Path(__file__).resolve().parent
sys.path.insert(0, str(task / "hidden" / "tests"))
from trk_encoder import encode  # noqa: E402
from trk_random import random_records  # noqa: E402

BE, DELTA, XOR, SUM = 1, 2, 4, 8
rng = random.Random(20261122)


def fix(t, lat, lon, alt):
    return {"type": "fix", "t": t, "lat": lat, "lon": lon, "alt": alt}


def note(t, text):
    return {"type": "note", "t": t, "text": text}


def battery(t, percent, mv=None):
    record = {"type": "battery", "t": t, "percent": percent}
    if mv is not None:
        record["mv"] = mv
    return record


def lap(t, n, seconds):
    return {"type": "lap", "t": t, "n": n, "seconds": seconds}


def walk(t, count, version, kinds, backwards=False, laps=(1, 2, 3)):
    """`count` records of the given kinds, times going forwards (and back once if asked)."""
    records = []
    lat, lon, alt = rng.uniform(40, 55), rng.uniform(5, 15), rng.uniform(200, 900)
    lap_numbers = iter(laps)
    for index in range(count):
        t += rng.choice([1, 2, 5, 10, 30, 60])
        if backwards and index == count // 2:
            t -= 75
        kind = kinds[index % len(kinds)]
        if kind == "fix":
            lat, lon, alt = lat + rng.uniform(-0.001, 0.001), lon + rng.uniform(-0.001, 0.001), alt + rng.uniform(-3, 3)
            records.append(fix(t, round(lat, 6), round(lon, 6), round(alt, 1)))
        elif kind == "note":
            records.append(note(t, rng.choice(["start", "bridge", "north gate", "pause", "wet", "km 5", "ok"])))
        elif kind == "battery":
            records.append(battery(t, rng.randint(20, 100), rng.randint(3400, 4200) if version == 2 else None))
        else:
            records.append(lap(t, next(lap_numbers, 9), round(rng.uniform(40, 400), 2)))
    return records


T0 = 1718003600
long_text = "Stopped at the hut above the pass: fog coming in from the west, path iced over past the second marker, turning back to the car park and trying the lower route tomorrow."
samples = [
    ("01-morning-run", "TR-200", 1, 0, [fix(T0, 47.376887, 8.541694, 408.0)] + walk(T0, 6, 1, ["fix", "fix", "battery"])),
    ("02-trail-notes", "TR-200", 1, 0, walk(T0 + 9000, 7, 1, ["note", "fix", "note"])),
    ("03-commute", "unit 7", 1, 0, walk(T0 + 86400, 9, 1, ["fix", "battery", "note", "fix"])),
    ("04-empty", "TR-200", 1, 0, []),
    ("05-harbour", "TR-310", 1, BE, walk(T0 + 100000, 6, 1, ["fix", "battery", "fix"])),
    ("06-ridge", "TR-200", 1, DELTA, walk(T0 + 200000, 8, 1, ["fix", "fix", "note"])),
    ("07-clock-fix", "TR-200", 1, DELTA, walk(T0 + 300000, 8, 1, ["fix", "battery"], backwards=True)),
    ("08-private", "TR-200", 1, XOR, walk(T0 + 400000, 6, 1, ["note", "fix"])),
    ("09-checked", "TR-200", 1, SUM, walk(T0 + 500000, 6, 1, ["fix", "battery", "note"])),
    ("10-track-laps", "TR-200", 1, 0, walk(T0 + 600000, 8, 1, ["lap", "fix"], laps=(1, 2, 3, 4))),
    ("11-long-note", "TR-200", 1, 0, [note(T0 + 700000, long_text), fix(T0 + 700030, 46.5586, 8.5614, 2106.4)]),
    ("12-velodrome", "TR-310", 1, BE, walk(T0 + 800000, 6, 1, ["lap", "battery"], laps=(126, 127, 128))),
    ("13-new-firmware", "TR-400", 2, 0, walk(T0 + 900000, 9, 2, ["fix", "battery", "note"])),
    ("14-new-harbour", "TR-400", 2, BE, walk(T0 + 1000000, 9, 2, ["battery", "note", "fix", "lap"])),
    ("15-new-private", "TR-400", 2, XOR | SUM, walk(T0 + 1100000, 8, 2, ["note", "battery", "fix"])),
    ("16-new-ridge", "TR-400", 2, DELTA, walk(T0 + 1200000, 9, 2, ["fix", "note", "battery"])),
    ("17-ferry", "TR-310", 1, BE | DELTA, walk(T0 + 1300000, 9, 1, ["fix", "lap", "note"], laps=(1, 300))),
    ("18-everything", "TR-310", 1, BE | DELTA | XOR | SUM, walk(T0 + 1400000, 10, 1, ["fix", "note", "battery", "lap"])),
    ("19-long-day", "TR-400", 2, BE | DELTA | XOR | SUM, walk(T0 + 1500000, 140, 2, ["fix", "fix", "fix", "battery", "note", "lap"], backwards=True, laps=range(1, 40))),
    ("20-dead-sea", "TR-200", 1, 0, [fix(T0 + 1600000, 31.559, 35.4732, -428.6), fix(T0 + 1600060, -33.918861, -70.650772, 12.3), fix(T0 + 1600120, -0.000012, -179.5, -0.4)]),
    ("21-kueche", "Küche 2", 1, XOR | SUM, walk(T0 + 1700000, 5, 1, ["note", "fix"]) + [note(T0 + 1700900, "café Zürich 日本")]),
    ("22-new-checked", "TR-400", 2, BE | SUM, walk(T0 + 1800000, 7, 2, ["fix", "battery", "lap"], laps=(20000, 2))),
    ("23-new-private-ridge", "TR-400", 2, DELTA | XOR, walk(T0 + 1900000, 8, 2, ["note", "fix", "battery"])),
    ("24-expedition", "TR-200", 1, DELTA | SUM, [fix(T0, 61.0, 7.0, 15.0), fix(T0 + 70000, 61.2, 7.1, 480.5), note(T0 + 70127, "camp"), fix(T0 + 70255, 61.21, 7.11, 482.0), battery(T0 + 4000000, 12)]),
]
assert len(samples) == 24

for folder in (task / "repo" / "samples", task / "hidden" / "samples"):
    (folder / "bad").mkdir(parents=True, exist_ok=True)
    for name, device, version, flags, records in samples:
        (folder / f"{name}.trk").write_bytes(encode(device, records, version, flags))
        shown = {"version": version, "device": device, "records": records}
        (folder / f"{name}.json").write_text(json.dumps(shown, indent=1, ensure_ascii=False) + "\n", "utf-8")
    good = encode("TR-200", walk(T0 + 50, 5, 1, ["fix", "note"]), 1, 0)
    checked = encode("TR-400", walk(T0 + 60, 5, 2, ["fix", "battery"]), 2, SUM)
    damaged = bytearray(checked)
    damaged[20] ^= 0x10
    unknown = bytearray(good)
    unknown[6 + 1 + 6 + 1] = 9  # the first record's kind
    bad = {
        "cut-short": (good[:-7], "File is truncated."),
        "left-over": (good + b"\x00\x00\x00", "Unexpected data after last record."),
        "bad-checksum": (bytes(damaged), "Checksum error: file is damaged."),
        "unknown-record": (bytes(unknown), "Unknown record type 9."),
    }
    for name, (data, message) in bad.items():
        (folder / "bad" / f"{name}.trk").write_bytes(data)
        (folder / "bad" / f"{name}.error").write_text(message + "\n", "utf-8")
print("samples written:", len(samples))
