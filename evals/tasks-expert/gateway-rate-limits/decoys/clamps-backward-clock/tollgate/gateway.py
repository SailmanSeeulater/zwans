"""The gateway: authenticate, route, rate-limit, forward."""

import logging

from tollgate.clock import Clock
from tollgate.config import Config, Plan, parse_config
from tollgate.http import Request, Response
from tollgate.limiter import RateLimiter
from tollgate.routing import Router
from tollgate.stats import StatsBook
from tollgate.upstreams import Upstream

log = logging.getLogger("tollgate")

KEY_HEADER = "X-Api-Key"
STATS_PATH = "/_stats"


class Gateway:
    def __init__(self, config: str | Config, upstreams: dict[str, Upstream], clock: Clock) -> None:
        self.config = parse_config(config) if isinstance(config, str) else config
        self.router = Router(self.config.routes)
        self.upstreams = dict(upstreams)
        self.clock = clock
        self.limiter = RateLimiter()
        self.stats = StatsBook()
        self._last_reading: float | None = None
        self._time = 0.0

    # -- requests

    def handle(self, request: Request) -> Response:
        now = self._now()
        self._forget_idle(now)

        key = request.header(KEY_HEADER)
        if (
            request.method == "GET"
            and request.path == STATS_PATH
            and self.config.stats_key is not None
            and key == self.config.stats_key
        ):
            return Response.json_body(200, self.report())

        if key is None:
            return Response.error(401, "missing API key")
        plan = self.config.plan_for(key)
        if plan is None:
            return Response.error(401, "unknown API key")

        match = self.router.match(request.method, request.path)
        if match.route is None:
            return Response.error(404, "no route for this path")
        if not match.method_allowed:
            return Response.error(405, f"{request.method} not allowed here")

        decision = self.limiter.check(key, plan, now)
        if not decision.allowed:
            self.stats.rejected(key, plan.name)
            return Response.error(
                429, "rate limit exceeded", {"Retry-After": str(decision.retry_after)}
            )
        self.stats.allowed(key, plan.name)
        return self._forward(match.route.upstream, request.with_path(
            self.router.upstream_path(match.route, request.path)
        ))

    def _now(self) -> float:
        """The gateway's own time: it moves forward with the clock and never goes back."""
        reading = self.clock.now()
        if self._last_reading is None or reading > self._time:
            self._time = reading
        self._last_reading = reading
        return self._time

    def _forward(self, name: str, request: Request) -> Response:
        upstream = self.upstreams.get(name)
        if upstream is None:
            log.warning("route points at unknown upstream %r", name)
            return Response.error(502, f"no upstream called {name}")
        try:
            return upstream.handle(request)
        except Exception as error:  # an upstream failing must not take the gateway down
            log.warning("upstream %s failed: %s", name, error)
            return Response.error(502, f"upstream {name} failed")

    # -- keys

    def _forget_idle(self, now: float) -> None:
        for key in self.limiter.keys():
            last = self.limiter.last_active(key)
            if last is not None and now - last >= self.config.idle_after:
                self._forget(key)

    def _forget(self, key: str) -> None:
        self.limiter.forget(key)
        self.stats.forget(key)

    def report(self) -> dict[str, object]:
        held = {key: self.limiter.held(key) for key in self.limiter.keys()}
        return self.stats.report(held)

    # -- config

    def reload(self, text: str) -> None:
        new = parse_config(text)  # raises ConfigError, leaving everything as it was
        old = self.config
        for key in set(self.limiter.keys()) | set(self.stats.keys()):
            new_plan: Plan | None = new.plan_for(key)
            if new_plan is None:
                self._forget(key)
                continue
            old_plan = old.plan_for(key)
            if old_plan is not None and old_plan != new_plan:
                self.limiter.replan(key, old_plan, new_plan)
            self.stats.replan(key, new_plan.name)
        self.config = new
        self.router = Router(new.routes)
        log.info("config reloaded: %d keys, %d routes", len(new.keys), len(new.routes))
