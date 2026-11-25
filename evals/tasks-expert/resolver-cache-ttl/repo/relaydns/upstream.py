"""The upstream server the resolver asks. FakeUpstream stands in for the real UDP client."""

import asyncio
from typing import Protocol

from relaydns.records import check_type, normalize
from relaydns.zone import Reply, Zone


class UpstreamError(Exception):
    """The upstream couldn't be reached, or didn't answer in time."""


class Upstream(Protocol):
    async def query(self, name: str, rtype: str) -> Reply: ...


class FakeUpstream:
    """Answers from a Zone.

    - `requests` counts every request received, failed ones included.
    - `down = True` makes every request fail; names in `failing` fail on their own.
    - With `hold = True`, requests wait until `release()` is called, so a test can decide
      when the replies arrive. Otherwise each reply comes after one turn of the event loop.
    The reply is worked out when the request arrives.
    """

    def __init__(self, zone: Zone, hold: bool = False) -> None:
        self.zone = zone
        self.hold = hold
        self.down = False
        self.failing: set[str] = set()
        self.requests = 0
        self.log: list[tuple[str, str]] = []
        self._pending: list[tuple[asyncio.Future[Reply], Reply | None]] = []

    async def query(self, name: str, rtype: str) -> Reply:
        name, rtype = normalize(name), check_type(rtype)
        self.requests += 1
        self.log.append((name, rtype))
        reply = None if self.down or name in self.failing else self.zone.lookup(name, rtype)
        if self.hold:
            future: asyncio.Future[Reply] = asyncio.get_running_loop().create_future()
            self._pending.append((future, reply))
            return await future
        await asyncio.sleep(0)
        if reply is None:
            raise UpstreamError(f"no answer for {name} {rtype}")
        return reply

    @property
    def pending(self) -> int:
        return len(self._pending)

    def release(self) -> int:
        """Deliver every reply held so far. Returns how many there were."""
        pending, self._pending = self._pending, []
        for future, reply in pending:
            if future.done():
                continue
            if reply is None:
                future.set_exception(UpstreamError("no answer"))
            else:
                future.set_result(reply)
        return len(pending)
