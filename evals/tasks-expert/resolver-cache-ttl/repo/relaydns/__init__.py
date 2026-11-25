"""relaydns: a caching resolver in front of an upstream DNS server."""

from relaydns.clock import ManualClock, MonotonicClock
from relaydns.message import NOERROR, NXDOMAIN, SERVFAIL, Answer
from relaydns.records import BadName, Record, Soa, normalize
from relaydns.resolver import Resolver
from relaydns.upstream import UpstreamError
from relaydns.zone import Zone, ZoneError

__all__ = [
    "NOERROR",
    "NXDOMAIN",
    "SERVFAIL",
    "Answer",
    "BadName",
    "ManualClock",
    "MonotonicClock",
    "Record",
    "Resolver",
    "Soa",
    "UpstreamError",
    "Zone",
    "ZoneError",
    "normalize",
]
