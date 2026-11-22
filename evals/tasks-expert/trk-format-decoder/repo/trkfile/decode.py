"""Reads .trk files, the logger's export format.

The vendor's description of the format is lost. This much was worked out from the first few
sample files; it reads those and refuses the rest.
"""

from typing import Any

MAGIC = b"TRK\x1a"


class TrkError(ValueError):
    """The bytes aren't a .trk file the vendor's tool would accept."""


def decode(data: bytes) -> dict[str, Any]:
    """The file as {"version", "device", "records"}, in the shape of the samples' .json."""
    if data[:4] != MAGIC:
        raise TrkError("not a .trk file")
    version, flags = data[4], data[5]
    if version != 1 or flags != 0:
        raise TrkError(f"version {version} with flags {flags:#x} isn't supported yet")
    position = 6
    length = data[position]
    device = data[position + 1 : position + 1 + length].decode("utf-8")
    position += 1 + length
    count = data[position]
    position += 1
    records: list[dict[str, Any]] = []
    for _ in range(count):
        kind = data[position]
        t = int.from_bytes(data[position + 1 : position + 5], "little")
        position += 5
        if kind == 1:
            lat = int.from_bytes(data[position : position + 4], "little", signed=True)
            lon = int.from_bytes(data[position + 4 : position + 8], "little", signed=True)
            alt = int.from_bytes(data[position + 8 : position + 10], "little")
            position += 10
            records.append(
                {"type": "fix", "t": t, "lat": lat / 1_000_000, "lon": lon / 1_000_000, "alt": alt / 10}
            )
        elif kind == 2:
            length = data[position]
            text = data[position + 1 : position + 1 + length].decode("utf-8")
            position += 1 + length
            records.append({"type": "note", "t": t, "text": text})
        elif kind == 3:
            records.append({"type": "battery", "t": t, "percent": data[position]})
            position += 1
        else:
            raise TrkError(f"record kind {kind} isn't supported yet")
    return {"version": version, "device": device, "records": records}
