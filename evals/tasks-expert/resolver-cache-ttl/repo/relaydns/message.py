"""What the resolver hands back to a client."""

from dataclasses import dataclass, field

from relaydns.records import Record

NOERROR = "NOERROR"
NXDOMAIN = "NXDOMAIN"
SERVFAIL = "SERVFAIL"


@dataclass(frozen=True)
class Answer:
    rcode: str
    records: tuple[Record, ...] = field(default_factory=tuple)
    soa: Record | None = None

    @classmethod
    def servfail(cls) -> "Answer":
        return cls(SERVFAIL)

    @property
    def negative(self) -> bool:
        return self.soa is not None

    def final(self, rtype: str) -> list[Record]:
        """The records of the type asked for, without the chain's CNAMEs."""
        return [record for record in self.records if record.rtype == rtype]

    def cnames(self) -> list[Record]:
        return [record for record in self.records if record.rtype == "CNAME"]

    def ttls(self) -> list[int]:
        ttls = [record.ttl for record in self.records]
        if self.soa is not None:
            ttls.append(self.soa.ttl)
        return ttls

    def render(self) -> str:
        lines = [f";; status: {self.rcode}"]
        if self.records:
            lines.append(";; ANSWER")
            lines += [record.text() for record in self.records]
        if self.soa is not None:
            lines.append(";; AUTHORITY")
            lines.append(self.soa.text())
        return "\n".join(lines)
