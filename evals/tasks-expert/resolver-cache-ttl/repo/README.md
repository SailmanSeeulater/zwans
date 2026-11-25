# relaydns

A caching DNS resolver for our internal service names. Clients ask it for a name and a record
type; it asks the upstream server, follows CNAME chains, and caches what it learns so that
repeated questions don't go upstream again.

```python
import asyncio
from relaydns import ManualClock, Resolver, Zone
from relaydns.upstream import FakeUpstream

zone = Zone.parse("""
$SOA example. 3600 ns1.example. hostmaster.example. 1 60
www.example.    300  CNAME  web.example.
web.example.     60  A      192.0.2.10
""")
resolver = Resolver(FakeUpstream(zone), ManualClock())
answer = asyncio.run(resolver.resolve("www.example.", "A"))
print(answer.render())
```

The upstream in production is a UDP client; in tests and in `python -m relaydns` it is
`FakeUpstream`, which answers from a `Zone`, counts every request it receives in
`upstream.requests`, can be made to fail, and can hold requests until the test releases them.

## What the upstream says

The upstream answers one name at a time. A request for a name and type gets one of:

- the records of that type at that name;
- the name's CNAME record, when the name is an alias (unless the type asked for is `CNAME`
  itself, which gets the CNAME record as its answer);
- `NXDOMAIN` (no such name) or `NODATA` (the name exists, but has no records of that type),
  each with the zone's SOA record;
- an `UpstreamError`, when the upstream can't be reached.

## Answers

`await resolver.resolve(name, type)` returns an `Answer`:

- `rcode`: `NOERROR`, `NXDOMAIN` or `SERVFAIL`;
- `records`: the CNAME records of the chain followed, in order, then the records of the type
  asked for (in the order the upstream gave them);
- `soa`: for `NXDOMAIN` and `NODATA` answers, the SOA record; otherwise `None`.

A positive answer is `NOERROR` with records of the type asked for. A *negative* answer is
`NXDOMAIN`, or `NODATA`: `NOERROR` with only the chain's CNAMEs (possibly none) and an SOA.

To resolve a name, the resolver asks the upstream for it; while the reply is a CNAME, it asks
for the CNAME's target, and so on, until it gets records, `NXDOMAIN` or `NODATA`. If a CNAME
points back to a name already in the chain, the chain is a loop: the resolver stops at once,
without asking for that name again, and the answer is `SERVFAIL` with no records.

Names are case-insensitive and always end with a dot; the resolver adds the dot if it is
missing.

## The cache

Answers are cached whole, under the name and type the client asked for. The names met along
a chain are not cached under their own names: asking for `www` caches the answer for `www`,
not one for `web`.

**An answer's lifetime** is how long it may be served from the cache, counted from the
moment it was fetched:

- for a positive answer, the smallest TTL among its records, CNAMEs included: a chain is only
  as fresh as its shortest-lived link;
- for a negative answer, the smallest of the chain's CNAME TTLs and the *negative TTL*: the
  smaller of the SOA record's own TTL and the SOA's `minimum` field, and never more than
  `max_negative_ttl` (a `Resolver` argument, 900 seconds unless given).

An answer is *fresh* while less than its lifetime has passed since it was fetched (fetched at
`f` with lifetime `L`: fresh while `now < f + L`). A query for a fresh answer is answered
from the cache without asking the upstream.

**TTLs count down.** Every record in an answer the client gets, the SOA included, shows the
same TTL: the time the answer has left, `f + L - now`. A freshly fetched answer shows its
whole lifetime; the same answer from the cache 20 seconds later shows 20 less.

A fetched answer replaces whatever was cached for that name and type. An answer with a
lifetime of 0 is passed on to the client and then not cached at all (so nothing is cached for
that name and type afterwards). A `SERVFAIL` is never cached and leaves the cache as it was.

The clock (`ManualClock` in tests) counts whole seconds.

## The upstream is shared

**One fetch at a time per question.** When a query arrives while the resolver is already
fetching an answer for the same name and type, it doesn't ask the upstream again: it waits
for that fetch and gets the same answer. Queries for different names or types are fetched
separately, even if their chains run through the same names.

## When the upstream fails

If the upstream raises `UpstreamError` while the resolver is fetching (at any step of a
chain), the fetch stops there, without retrying, and:

- if an answer for that name and type expired less than `serve_stale` seconds ago (a
  `Resolver` argument, 60 seconds unless given), the client gets that **stale** answer, with
  every TTL showing 30. Expired at `f + L`: usable while `now < f + L + serve_stale`. The cached
  answer stays as it was, so the next query tries the upstream again;
- otherwise the answer is `SERVFAIL`.

A chain that loops is not an upstream failure (the upstream did answer), so it never gets a
stale answer: it is `SERVFAIL`.

## Command line

```
python -m relaydns zone.txt www.example. A web.example. TXT
```

resolves each name and type against a `FakeUpstream` for the zone file and prints the answers.

## Zone files

One record per line: `name ttl type value`; `;` starts a comment. `$SOA apex ttl mname rname
serial minimum` sets the zone's SOA record. Types: `A`, `AAAA`, `CNAME`, `TXT`, `MX`.

## Tests

```
python -m pytest -q
```
