# tollgate

A small API gateway. It sits in front of our internal services, checks each caller's API key,
routes the request to the right upstream, and holds every key to the request rate its plan
allows. Plans, keys and routes come from a TOML file that can be reloaded without a restart.

```python
from tollgate import Gateway, Request, SystemClock
from tollgate.upstreams import EchoUpstream

gateway = Gateway(open("tollgate.toml").read(), {"orders": EchoUpstream("orders")}, SystemClock())
response = gateway.handle(Request("GET", "/orders/17", {"X-Api-Key": "k-alice"}))
response.status            # 200, or 401 / 404 / 405 / 429 / 502
```

## Configuration

```toml
[gateway]
idle_after = 900          # seconds; see "Idle keys"
stats_key = "ops-only"    # the key that may read /_stats

[plans.free]
limit = 10                # requests...
window = 60               # ...per this many seconds

[plans.pro]
limit = 100
window = 60

[keys]
"k-alice" = "pro"
"k-bob" = "free"

[[routes]]
prefix = "/orders"
upstream = "orders"
methods = ["GET", "POST"]   # optional; every method when left out
strip_prefix = false        # optional; true sends "/orders/17" upstream as "/17"
```

`limit` is a whole number, at least 1. `window` is a number of seconds greater than 0
(fractions are fine). `idle_after` defaults to 3600 and `stats_key` to no stats endpoint at
all. A config that breaks any of this raises `ConfigError`, both when the gateway is created
and on reload.

## Handling a request

`gateway.handle(request)` reads the clock **once**, whatever happens to the request, then:

1. Forgets idle keys (see "Idle keys").
2. `GET /_stats` with the stats key gets the stats (below). With any other key or method it
   is treated like any other path (no route may use the `/_stats` prefix).
3. A request without an `X-Api-Key` header, or with a key that isn't in `[keys]`, gets `401`.
4. A path no route serves gets `404`; a route that doesn't allow the method gives `405`. The
   route with the longest prefix wins; a prefix matches the path itself and anything under
   it (`/orders` matches `/orders` and `/orders/17`, not `/ordersx`).
5. The rate limit: a request over its key's limit gets `429` with a `Retry-After` header.
6. Otherwise the upstream answers. An upstream that is missing or raises gives `502`.

Only requests that get as far as step 5 count against the limit or keep a key active: a
`401`, `404` or `405` is as if the request never happened, as far as the limiter is concerned.

## Rate limits

Each key may make at most `limit` requests in **any** `window` seconds, sliding: there are no
fixed periods that start and end on the clock.

A request at time `t` is *allowed* when fewer than `limit` of the key's earlier allowed
requests happened less than `window` seconds before it, that is at a time `s` with
`t - s < window`. A request exactly `window` seconds after another no longer sees it. Rejected
requests don't count: a client hammering away while throttled is let back in as soon as its
allowed requests age out, as if the rejected ones had not been made.

A rejected request gets `429` and `Retry-After: n`, the number of seconds until a request
from the key would be allowed (if nothing else happens in between), rounded up to a whole
second.

### Memory

There can be a lot of keys, so the limiter keeps, for each key, the times of the key's most
recent allowed requests, **at most `limit` of them**, and nothing else that grows. A time is
dropped only when a newer allowed request pushes it out (the oldest goes first), when a
reload lowers the key's limit (the oldest go first), or when the key is forgotten. It is not
dropped just because it has left the window. The stats show the number of times kept for each
key as `held`, which is never more than the key's current limit.

## Time

The gateway takes the time from the clock it was given (`SystemClock`, or `ManualClock` in
tests). Server clocks get corrected, sometimes backwards, so the gateway keeps its own time
that never goes back:

- At the first request, the gateway's time is the clock reading.
- At each later request, the gateway's time moves forward by how much the clock reading went
  up since the previous request. If the reading went down, the gateway's time stays where it
  is, and the clock's progress from the new, lower reading counts from the next request on.

So a clock stepped back an hour costs nobody an hour: the gateway simply sees no time pass
across the step. Every time in this README (request times, `Retry-After`, idle times) is the
gateway's time.

## Reloading

`gateway.reload(text)` swaps in a new config. On `ConfigError` the old config stays.

- Keys keep their limiter history across a reload. If a key's plan changed (or its plan's
  `limit` or `window` did), the new `limit` and `window` apply from the next request on, to
  the times already kept: requests allowed before the reload still count, under the new
  window.
- When the new limit is lower, the oldest kept times are dropped down to the new limit.
  When it is higher, nothing comes back: times already dropped stay dropped.
- A key that is no longer in `[keys]` is forgotten, and its requests get `401`.

## Idle keys

A key is *active* at the time of its latest request that reached the rate limit (allowed or
rejected). At the start of each request, the gateway forgets every key that has not been
active for `idle_after` seconds or more (`t - last_active >= idle_after`). Forgetting a key
drops its kept times and its stats; if it comes back, it starts from nothing.

## Stats

`GET /_stats` with `X-Api-Key` set to the stats key answers `200` with JSON:

```json
{"keys": {"k-alice": {"plan": "pro", "allowed": 12, "rejected": 3, "held": 12}}}
```

One entry per key the gateway currently remembers (a key appears at its first request that
reaches the rate limit, and disappears when it is forgotten); the counts are since then. The
stats request itself counts for nothing but the clock reading and step 1.

## Replaying a log

```
python -m tollgate check tollgate.toml
python -m tollgate replay tollgate.toml requests.log
```

`replay` runs each line of the log (`<clock reading> <key> <method> <path>`) through a gateway
with echo upstreams for every route and prints the status of each.

## Tests

```
python -m pytest -q
```
