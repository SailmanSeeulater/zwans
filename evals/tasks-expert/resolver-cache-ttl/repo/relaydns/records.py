"""Names, types and resource records."""

from dataclasses import dataclass, replace

TYPES = ("A", "AAAA", "CNAME", "TXT", "MX", "SOA")


class BadName(ValueError):
    """A name or type the resolver can't use."""


def normalize(name: str) -> str:
    """Lower case, with exactly one trailing dot. The root is "."."""
    text = name.strip().lower()
    if not text or text == ".":
        return "."
    text = text.rstrip(".")
    labels = text.split(".")
    for label in labels:
        if not label:
            raise BadName(f"empty label in {name!r}")
        if len(label) > 63:
            raise BadName(f"label too long in {name!r}")
        if not all(ch.isalnum() or ch in "-_*" for ch in label):
            raise BadName(f"bad character in {name!r}")
    if len(text) > 253:
        raise BadName(f"name too long: {name!r}")
    return text + "."


def check_type(rtype: str) -> str:
    upper = rtype.strip().upper()
    if upper not in TYPES:
        raise BadName(f"unknown record type {rtype!r}")
    return upper


@dataclass(frozen=True)
class Record:
    name: str
    rtype: str
    ttl: int
    value: str

    def with_ttl(self, ttl: int) -> "Record":
        return replace(self, ttl=ttl)

    def text(self) -> str:
        return f"{self.name}\t{self.ttl}\tIN\t{self.rtype}\t{self.value}"


@dataclass(frozen=True)
class Soa:
    mname: str
    rname: str
    serial: int
    minimum: int

    @classmethod
    def of(cls, record: Record) -> "Soa":
        if record.rtype != "SOA":
            raise ValueError(f"not an SOA record: {record.text()}")
        mname, rname, serial, minimum = record.value.split()
        return cls(mname, rname, int(serial), int(minimum))

    def value(self) -> str:
        return f"{self.mname} {self.rname} {self.serial} {self.minimum}"


def soa_record(apex: str, ttl: int, mname: str, rname: str, serial: int, minimum: int) -> Record:
    soa = Soa(normalize(mname), normalize(rname), serial, minimum)
    return Record(normalize(apex), "SOA", ttl, soa.value())
