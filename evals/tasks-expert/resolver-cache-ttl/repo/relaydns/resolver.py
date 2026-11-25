"""The caching resolver."""

import logging
from dataclasses import dataclass

from relaydns.cache import Cache, Key
from relaydns.clock import Clock
from relaydns.message import NOERROR, NXDOMAIN, Answer
from relaydns.records import Record, Soa, check_type, normalize
from relaydns.upstream import Upstream, UpstreamError
from relaydns.zone import CNAME, NODATA, RECORDS, Reply

log = logging.getLogger("relaydns")


@dataclass
class Stats:
    queries: int = 0
    hits: int = 0
    fetches: int = 0
    stale: int = 0
    failures: int = 0


class Resolver:
    def __init__(
        self,
        upstream: Upstream,
        clock: Clock,
        *,
        max_negative_ttl: int = 900,
        serve_stale: int = 60,
        cache: Cache | None = None,
    ) -> None:
        self.upstream = upstream
        self.clock = clock
        self.max_negative_ttl = max_negative_ttl
        self.serve_stale = serve_stale
        self.cache = cache if cache is not None else Cache()
        self.stats = Stats()

    async def resolve(self, name: str, rtype: str) -> Answer:
        key: Key = (normalize(name), check_type(rtype))
        self.stats.queries += 1
        now = self.clock.now()
        entry = self.cache.get(key)
        if entry is not None and entry.fresh(now):
            self.stats.hits += 1
            return entry.answer

        self.stats.fetches += 1
        try:
            answer = await self._fetch(*key)
        except UpstreamError as error:
            log.info("upstream failed for %s %s: %s", key[0], key[1], error)
            if entry is not None:
                self.stats.stale += 1
                return entry.answer
            self.stats.failures += 1
            return Answer.servfail()

        lifetime = self._lifetime(answer)
        if lifetime > 0:
            self.cache.put(key, answer, now, lifetime)
        else:
            self.cache.drop(key)
        return answer

    async def _fetch(self, name: str, rtype: str) -> Answer:
        chain: list[Record] = []
        current = name
        while True:
            reply: Reply = await self.upstream.query(current, rtype)
            if reply.kind == CNAME:
                link = reply.records[0]
                chain.append(link)
                current = link.value
                continue
            if reply.kind == RECORDS:
                return Answer(NOERROR, tuple(chain) + reply.records)
            rcode = NOERROR if reply.kind == NODATA else NXDOMAIN
            return Answer(rcode, tuple(chain), reply.soa)

    def _lifetime(self, answer: Answer) -> int:
        if answer.soa is not None:
            return Soa.of(answer.soa).minimum
        return answer.records[0].ttl
