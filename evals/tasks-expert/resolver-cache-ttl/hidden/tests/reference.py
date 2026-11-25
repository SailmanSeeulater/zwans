"""A slow, obviously-right resolver for the tests to compare against, written from the README.
It keeps its own copy of the zone as a plain dict and shares no code with relaydns.

A zone here is {name: (type, ttl, values)}, with type "A", "TXT" or "CNAME" (one value, the
target), plus an SOA (ttl, minimum). Answers are compared as plain tuples:
(rcode, ((name, type, ttl, value), ...), (name, ttl, value) or None)."""

from dataclasses import dataclass, field

APEX = "example."
SOA_VALUE = "ns1.example. hostmaster.example. 1 {minimum}"
STALE_TTL = 30


@dataclass
class ZoneModel:
    names: dict[str, tuple[str, int, list[str]]] = field(default_factory=dict)
    soa_ttl: int = 3600
    soa_minimum: int = 60

    def text(self) -> str:
        lines = [f"$SOA {APEX} {self.soa_ttl} ns1.example. hostmaster.example. 1 {self.soa_minimum}"]
        for name, (rtype, ttl, values) in self.names.items():
            lines += [f"{name} {ttl} {rtype} {value}" for value in values]
        return "\n".join(lines) + "\n"

    def soa(self, ttl: int) -> tuple[str, int, str]:
        return (APEX, ttl, SOA_VALUE.format(minimum=self.soa_minimum))


def plain(answer) -> tuple:
    """A relaydns Answer as a tuple, for comparing."""
    records = tuple((r.name, r.rtype, r.ttl, r.value) for r in answer.records)
    soa = None if answer.soa is None else (answer.soa.name, answer.soa.ttl, answer.soa.value)
    return (answer.rcode, records, soa)


SERVFAIL = ("SERVFAIL", (), None)


@dataclass
class Cached:
    rcode: str
    records: list[tuple[str, str, int, str]]
    soa_minimum: int | None  # the SOA as fetched, if negative
    soa_ttl: int | None
    fetched: int
    lifetime: int

    def shown(self, ttl: int) -> tuple:
        records = tuple((name, rtype, ttl, value) for name, rtype, _, value in self.records)
        soa = None
        if self.soa_minimum is not None:
            soa = (APEX, ttl, SOA_VALUE.format(minimum=self.soa_minimum))
        return (self.rcode, records, soa)


class Reference:
    def __init__(self, max_negative_ttl: int = 900, serve_stale: int = 60) -> None:
        self.max_negative_ttl = max_negative_ttl
        self.serve_stale = serve_stale
        self.cache: dict[tuple[str, str], Cached] = {}

    def ask(
        self, zone: ZoneModel, name: str, rtype: str, now: int, down: bool, failing: set[str]
    ) -> tuple[tuple, int]:
        """One question (not one already being fetched). Returns (answer, upstream requests)."""
        key = (name, rtype)
        entry = self.cache.get(key)
        if entry is not None and now < entry.fetched + entry.lifetime:
            return entry.shown(entry.fetched + entry.lifetime - now), 0

        requests = 0
        chain: list[tuple[str, str, int, str]] = []
        seen = {name}
        current = name
        while True:
            requests += 1
            if down or current in failing:
                if entry is not None and now < entry.fetched + entry.lifetime + self.serve_stale:
                    return entry.shown(STALE_TTL), requests
                return SERVFAIL, requests
            found = zone.names.get(current)
            if found is not None and found[0] == "CNAME" and rtype != "CNAME":
                target = found[2][0]
                chain.append((current, "CNAME", found[1], target))
                if target in seen:
                    return SERVFAIL, requests
                seen.add(target)
                current = target
                continue
            break

        ttls = [ttl for _, _, ttl, _ in chain]
        if found is None or found[0] != rtype:
            rcode = "NXDOMAIN" if found is None else "NOERROR"
            negative = min(zone.soa_ttl, zone.soa_minimum, self.max_negative_ttl)
            lifetime = min(ttls + [negative])
            cached = Cached(rcode, chain, zone.soa_minimum, zone.soa_ttl, now, lifetime)
        else:
            records = chain + [(current, rtype, found[1], value) for value in found[2]]
            lifetime = min(ttl for _, _, ttl, _ in records)
            cached = Cached("NOERROR", records, None, None, now, lifetime)
        if lifetime > 0:
            self.cache[key] = cached
        else:
            self.cache.pop(key, None)
        return cached.shown(lifetime), requests
