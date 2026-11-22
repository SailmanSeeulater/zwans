"""Random logs for the tests: what a device might record, in the shape decode() returns."""

import random

WORDS = ["start", "café", "bridge", "north gate", "pause", "wet", "Zürich", "km 5", "ok", "日本"]


def random_records(rng: random.Random, version: int, count: int) -> list[dict]:
    records = []
    t = rng.randint(1_000, 1_900_000_000)
    for _ in range(count):
        # Mostly forwards, sometimes a long gap, now and then backwards (a clock correction).
        t = max(0, t + rng.choice([1, 5, 30, 90, 127, 128, 4_000, 70_000, -1, -64, -65, -3_000]))
        kind = rng.choice(["fix", "fix", "note", "battery", "lap"])
        if kind == "fix":
            record = {
                "type": "fix",
                "t": t,
                "lat": round(rng.uniform(-89.9, 89.9), 6),
                "lon": round(rng.uniform(-179.9, 179.9), 6),
                "alt": round(rng.uniform(-420.0, 3200.0), 1),
            }
        elif kind == "note":
            words = rng.choices(WORDS, k=rng.choice([0, 1, 2, 3, 8, 40]))
            record = {"type": "note", "t": t, "text": " ".join(words)}
        elif kind == "battery":
            record = {"type": "battery", "t": t, "percent": rng.randint(0, 100)}
            if version == 2:
                record["mv"] = rng.randint(3000, 4350)
        else:
            record = {
                "type": "lap",
                "t": t,
                "n": rng.choice([1, 2, 9, 127, 128, 300, 20_000]),
                "seconds": round(rng.uniform(0, 167_000), 2),
            }
        records.append(record)
    return records


def random_log(rng: random.Random) -> tuple[str, list[dict], int, int]:
    """A device name, its records, a version and a set of flags."""
    version = rng.choice([1, 2])
    flags = rng.randrange(16)
    device = rng.choice(["TR-200", "Küche", "unit 7", "", "X" * 40])
    return device, random_records(rng, version, rng.choice([0, 1, 2, 5, 12, 140])), version, flags
