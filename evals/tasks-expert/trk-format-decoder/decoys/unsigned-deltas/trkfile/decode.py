"""A tempting wrong answer: it reads all but two of the samples, because it takes the time steps as
unsigned, and only the two samples with a clock correction step backwards.

Reads .trk files, the logger's export format. The vendor's description of it is lost;
this follows what the files in samples/ show."""

from typing import Any

MAGIC = b"TRK\x1a"
BIG_ENDIAN, DELTA_TIMES, OBFUSCATED, CHECKSUM = 1, 2, 4, 8


class TrkError(ValueError):
    """The bytes aren't a .trk file the vendor's tool would accept."""


class _Reader:
    def __init__(self, data: bytes, order: str) -> None:
        self.data = data
        self.position = 0
        self.order = order

    def take(self, count: int) -> bytes:
        end = self.position + count
        if end > len(self.data):
            raise TrkError("the file is cut short")
        chunk = self.data[self.position : end]
        self.position = end
        return chunk

    def number(self, size: int, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), self.order, signed=signed)  # type: ignore[arg-type]

    def varint(self) -> int:
        value, shift = 0, 0
        while True:
            byte = self.take(1)[0]
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value
            shift += 7
            if shift > 63:
                raise TrkError("a number runs on too long")


def decode(data: bytes) -> dict[str, Any]:
    """The file as {"version", "device", "records"}. Raises TrkError for a file that is cut
    short, has bytes left over, fails its checksum, or holds something unknown."""
    if data[:4] != MAGIC:
        raise TrkError("not a .trk file")
    if len(data) < 6:
        raise TrkError("the file is cut short")
    version, flags = data[4], data[5]
    if version not in (1, 2):
        raise TrkError(f"unknown version {version}")
    if flags & ~(BIG_ENDIAN | DELTA_TIMES | OBFUSCATED | CHECKSUM):
        raise TrkError(f"unknown flags {flags:#x}")
    order = "big" if flags & BIG_ENDIAN else "little"
    if flags & CHECKSUM:
        if len(data) < 8:
            raise TrkError("the file is cut short")
        body, stored = data[:-2], int.from_bytes(data[-2:], order)  # type: ignore[arg-type]
        if sum(body) % 65536 != stored:
            raise TrkError("checksum mismatch")
        data = body
    reader = _Reader(data, order)
    reader.position = 6

    def text(raw: bytes) -> str:
        if flags & OBFUSCATED:
            raw = bytes(b ^ 0x5A for b in raw)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TrkError("text that isn't UTF-8") from exc

    device = text(reader.take(reader.number(1)))
    records: list[dict[str, Any]] = []
    previous = 0
    for index in range(reader.varint()):
        kind = reader.number(1)
        if flags & DELTA_TIMES and index > 0:
            raw = reader.varint()
            t = previous + raw // 2  # the samples' steps are all stored doubled
        else:
            t = reader.number(4)
        previous = t
        if kind == 1:
            lat = reader.number(4, signed=True)
            lon = reader.number(4, signed=True)
            alt = reader.number(2, signed=True)
            record = {
                "type": "fix",
                "t": t,
                "lat": round(lat / 1_000_000, 6),
                "lon": round(lon / 1_000_000, 6),
                "alt": round(alt / 10, 1),
            }
        elif kind == 2:
            length = reader.number(2) if version == 2 else reader.varint()
            record = {"type": "note", "t": t, "text": text(reader.take(length))}
        elif kind == 3:
            record = {"type": "battery", "t": t, "percent": reader.number(1)}
            if version == 2:
                record["mv"] = reader.number(2)
        elif kind == 4:
            number = reader.varint()
            record = {"type": "lap", "t": t, "n": number, "seconds": round(reader.number(3) / 100, 2)}
        else:
            raise TrkError(f"unknown record kind {kind}")
        records.append(record)
    if reader.position != len(data):
        raise TrkError("bytes left over after the last record")
    return {"version": version, "device": device, "records": records}
