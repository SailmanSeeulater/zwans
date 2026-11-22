"""Writes .trk files, as the vendor's logger does. The tests make fresh files with it and
check that the decoder under test reads them back. Never shown to the agent: the task is to
work the format out from the samples.

    file    = "TRK\\x1a"  version:u8  flags:u8  device  count:varint  record*  [checksum:u16]
    device  = length:u8  utf-8 bytes
    flags   = 1: numbers are big-endian (else little-endian)
              2: each record's time is a signed change from the record before (zigzag
                 varint); the first is still absolute
              4: every string's bytes are XORed with 0x5A (the device name too)
              8: the file ends with a checksum: the sum of every byte before it, mod 65536
    record  = kind:u8  time  payload
    time    = u32 seconds, or with flag 2 after the first record, a zigzag varint
    kind 1  fix:      lat:i32 (millionths of a degree)  lon:i32  alt:i16 (tenths of a metre)
    kind 2  note:     text (version 1: varint length; version 2: u16 length), then the bytes
    kind 3  battery:  percent:u8, and in version 2 also millivolts:u16
    kind 4  lap:      number:varint  duration:u24 (hundredths of a second)

Varints are little-endian base 128 whatever flag 1 says.
"""

BIG_ENDIAN, DELTA_TIMES, OBFUSCATED, CHECKSUM = 1, 2, 4, 8
MAGIC = b"TRK\x1a"
KINDS = {"fix": 1, "note": 2, "battery": 3, "lap": 4}


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63)


def encode(device: str, records: list[dict], version: int = 1, flags: int = 0) -> bytes:
    order = "big" if flags & BIG_ENDIAN else "little"

    def number(value: int, size: int, signed: bool = False) -> bytes:
        return value.to_bytes(size, order, signed=signed)

    def text(value: str) -> bytes:
        raw = value.encode("utf-8")
        return bytes(b ^ 0x5A for b in raw) if flags & OBFUSCATED else raw

    name = text(device)
    out = bytearray(MAGIC + bytes([version, flags, len(name)]) + name + varint(len(records)))
    previous = 0
    for index, record in enumerate(records):
        out.append(KINDS[record["type"]])
        if flags & DELTA_TIMES and index > 0:
            out += varint(zigzag(record["t"] - previous))
        else:
            out += number(record["t"], 4)
        previous = record["t"]
        kind = record["type"]
        if kind == "fix":
            out += number(round(record["lat"] * 1_000_000), 4, signed=True)
            out += number(round(record["lon"] * 1_000_000), 4, signed=True)
            out += number(round(record["alt"] * 10), 2, signed=True)
        elif kind == "note":
            body = text(record["text"])
            out += (number(len(body), 2) if version == 2 else varint(len(body))) + body
        elif kind == "battery":
            out.append(record["percent"])
            if version == 2:
                out += number(record["mv"], 2)
        else:
            out += varint(record["n"]) + number(round(record["seconds"] * 100), 3)
    if flags & CHECKSUM:
        out += number(sum(out) % 65536, 2)
    return bytes(out)
