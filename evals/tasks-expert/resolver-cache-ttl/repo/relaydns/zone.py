"""The data an upstream answers from: records, and the zone's SOA."""

from dataclasses import dataclass, field

from relaydns.records import Record, check_type, normalize, soa_record

RECORDS = "records"
CNAME = "cname"
NXDOMAIN = "nxdomain"
NODATA = "nodata"


class ZoneError(ValueError):
    pass


@dataclass(frozen=True)
class Reply:
    """What the upstream says about one name and type."""

    kind: str
    records: tuple[Record, ...] = ()
    soa: Record | None = None


@dataclass
class Zone:
    soa: Record | None = None
    records: list[Record] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> "Zone":
        zone = cls()
        for number, raw in enumerate(text.splitlines(), start=1):
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            try:
                if parts[0].upper() == "$SOA":
                    if len(parts) != 7:
                        raise ZoneError("$SOA needs: apex ttl mname rname serial minimum")
                    apex, ttl, mname, rname, serial, minimum = parts[1:]
                    zone.soa = soa_record(apex, _ttl(ttl), mname, rname, int(serial), int(minimum))
                    continue
                if len(parts) < 4:
                    raise ZoneError("expected: name ttl type value")
                name, ttl, rtype = parts[0], parts[1], parts[2]
                value = " ".join(parts[3:])
                zone.add(name, _ttl(ttl), rtype, value)
            except (ZoneError, ValueError) as error:
                raise ZoneError(f"line {number}: {error}") from None
        return zone

    def add(self, name: str, ttl: int, rtype: str, value: str) -> None:
        name, rtype = normalize(name), check_type(rtype)
        if rtype == "SOA":
            raise ZoneError("use $SOA for the zone's SOA record")
        if rtype == "CNAME":
            value = normalize(value)
            if any(r.name == name for r in self.records):
                raise ZoneError(f"{name} has other records, so it can't have a CNAME")
        elif any(r.name == name and r.rtype == "CNAME" for r in self.records):
            raise ZoneError(f"{name} is an alias (CNAME), so it can't have other records")
        self.records.append(Record(name, rtype, ttl, value))

    def remove(self, name: str, rtype: str | None = None) -> None:
        name = normalize(name)
        self.records = [
            r for r in self.records if not (r.name == name and (rtype is None or r.rtype == rtype))
        ]

    def replace(self, name: str, ttl: int, rtype: str, *values: str) -> None:
        """Set a name's records of one type (removing the name's other records if the new
        type is CNAME, or the name's CNAME if it isn't)."""
        name, rtype = normalize(name), check_type(rtype)
        if rtype == "CNAME":
            self.remove(name)
        else:
            self.remove(name, "CNAME")
            self.remove(name, rtype)
        for value in values:
            self.add(name, ttl, rtype, value)

    def names(self) -> list[str]:
        seen: dict[str, None] = {}
        for record in self.records:
            seen.setdefault(record.name, None)
        return list(seen)

    def lookup(self, name: str, rtype: str) -> Reply:
        name, rtype = normalize(name), check_type(rtype)
        at_name = [r for r in self.records if r.name == name]
        if not at_name:
            return Reply(NXDOMAIN, (), self._soa())
        matching = tuple(r for r in at_name if r.rtype == rtype)
        if matching:
            return Reply(RECORDS, matching)
        cname = [r for r in at_name if r.rtype == "CNAME"]
        if cname:
            return Reply(CNAME, (cname[0],))
        return Reply(NODATA, (), self._soa())

    def _soa(self) -> Record:
        if self.soa is None:
            raise ZoneError("the zone has no $SOA, so it can't give a negative answer")
        return self.soa


def _ttl(text: str) -> int:
    ttl = int(text)
    if ttl < 0 or ttl > 2**31 - 1:
        raise ZoneError(f"bad TTL {text}")
    return ttl
