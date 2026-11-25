"""The caching resolver."""

import asyncio
import logging
from dataclasses import dataclass

from relaydns.cache import Cache, Entry, Key
from relaydns.clock import Clock
from relaydns.message import NOERROR, NXDOMAIN, Answer
from relaydns.records import Record, Soa, check_type, normalize
from relaydns.upstream import Upstream, UpstreamError
from relaydns.zone import CNAME, NODATA, RECORDS, Reply

log = logging.getLogger("relaydns")

STALE_TTL = 30


class ChainLoop(Exception):
    pass


@dataclass
class Stats:
    queries: int = 0
    hits: int = 0
    fetches: int = 0
    stale: int = 0
    failures: int = 0


def with_ttl(answer: Answer, ttl: int) -> Answer:
    records = tuple(record.with_ttl(ttl) for record in answer.records)
    soa = None if answer.soa is None else answer.soa.with_ttl(ttl)
    return Answer(answer.rcode, records, soa)


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
        self._fetching: dict[Key, asyncio.Task[Answer]] = {}

    async def resolve(self, name: str, rtype: str) -> Answer:
        key: Key = (normalize(name), check_type(rtype))
        self.stats.queries += 1
        now = self.clock.now()
        entry = self.cache.get(key)
        if entry is not None and entry.fresh(now):
            self.stats.hits += 1
            return with_ttl(entry.answer, entry.expires - now)

        task = self._fetching.get(key)
        if task is None:
            task = asyncio.ensure_future(self._refresh(key))
            self._fetching[key] = task
        return await asyncio.shield(task)

    async def _refresh(self, key: Key) -> Answer:
        try:
            self.stats.fetches += 1
            try:
                answer = await self._fetch(*key)
            except ChainLoop:
                self.stats.failures += 1
                return Answer.servfail()
            except UpstreamError as error:
                log.info("upstream failed for %s %s: %s", key[0], key[1], error)
                return self._stale_or_fail(key)
            now = self.clock.now()
            lifetime = self._lifetime(answer)
            if lifetime > 0:
                self.cache.put(key, answer, now, lifetime)
            else:
                self.cache.drop(key)
            return with_ttl(answer, lifetime)
        finally:
            self._fetching.pop(key, None)

    def _stale_or_fail(self, key: Key) -> Answer:
        now = self.clock.now()
        entry: Entry | None = self.cache.get(key)
        if entry is not None:
            self.stats.stale += 1
            return with_ttl(entry.answer, STALE_TTL)
        self.stats.failures += 1
        return Answer.servfail()

    async def _fetch(self, name: str, rtype: str) -> Answer:
        chain: list[Record] = []
        seen = {name}
        current = name
        while True:
            reply: Reply = await self.upstream.query(current, rtype)
            if reply.kind == CNAME:
                link = reply.records[0]
                chain.append(link)
                if link.value in seen:
                    raise ChainLoop(link.value)
                seen.add(link.value)
                current = link.value
                continue
            if reply.kind == RECORDS:
                return Answer(NOERROR, tuple(chain) + reply.records)
            rcode = NOERROR if reply.kind == NODATA else NXDOMAIN
            return Answer(rcode, tuple(chain), reply.soa)

    def _lifetime(self, answer: Answer) -> int:
        ttls = [record.ttl for record in answer.records]
        if answer.soa is not None:
            soa = Soa.of(answer.soa)
            ttls.append(min(answer.soa.ttl, soa.minimum, self.max_negative_ttl))
        return min(ttls)
