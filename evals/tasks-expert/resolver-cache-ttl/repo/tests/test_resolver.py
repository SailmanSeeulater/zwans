import asyncio

from relaydns import NOERROR, NXDOMAIN, SERVFAIL, ManualClock, Resolver, Zone
from relaydns.cli import main
from relaydns.upstream import FakeUpstream

ZONE = """
$SOA example. 3600 ns1.example. hostmaster.example. 1 120
www.example.     300  CNAME  web.example.
web.example.      60  A      192.0.2.10
web.example.      60  A      192.0.2.11
api.example.      90  AAAA   2001:db8::5
"""


def setup(text: str = ZONE) -> tuple[Resolver, FakeUpstream, ManualClock]:
    upstream = FakeUpstream(Zone.parse(text))
    clock = ManualClock(1000)
    return Resolver(upstream, clock), upstream, clock


def resolve(resolver: Resolver, name: str, rtype: str = "A"):
    return asyncio.run(resolver.resolve(name, rtype))


def test_a_plain_answer() -> None:
    resolver, upstream, _ = setup()

    answer = resolve(resolver, "web.example")

    assert answer.rcode == NOERROR
    assert [(r.name, r.ttl, r.value) for r in answer.records] == [
        ("web.example.", 60, "192.0.2.10"),
        ("web.example.", 60, "192.0.2.11"),
    ]
    assert answer.soa is None
    assert upstream.requests == 1


def test_a_cached_answer_doesnt_go_upstream() -> None:
    resolver, upstream, clock = setup()
    resolve(resolver, "api.example.", "AAAA")

    clock.advance(30)
    again = resolve(resolver, "API.example.", "aaaa")

    assert again.final("AAAA")[0].value == "2001:db8::5"
    assert upstream.requests == 1


def test_an_expired_answer_is_fetched_again() -> None:
    resolver, upstream, clock = setup()
    resolve(resolver, "api.example.", "AAAA")

    clock.advance(90)
    resolve(resolver, "api.example.", "AAAA")

    assert upstream.requests == 2


def test_a_chain_is_followed() -> None:
    resolver, upstream, _ = setup()

    answer = resolve(resolver, "www.example.")

    assert [r.rtype for r in answer.records] == ["CNAME", "A", "A"]
    assert answer.cnames()[0].value == "web.example."
    assert upstream.log == [("www.example.", "A"), ("web.example.", "A")]


def test_negative_answers() -> None:
    resolver, _, _ = setup()

    missing = resolve(resolver, "nope.example.")
    nodata = resolve(resolver, "web.example.", "MX")

    assert missing.rcode == NXDOMAIN and missing.records == ()
    assert missing.soa is not None and missing.soa.rtype == "SOA"
    assert nodata.rcode == NOERROR and nodata.records == () and nodata.soa is not None


def test_no_upstream_and_nothing_cached_is_a_servfail() -> None:
    resolver, upstream, _ = setup()
    upstream.down = True

    answer = resolve(resolver, "web.example.")

    assert answer.rcode == SERVFAIL and answer.records == ()


def test_render() -> None:
    resolver, _, _ = setup()

    text = resolve(resolver, "web.example.").render()

    assert text.splitlines()[0] == ";; status: NOERROR"
    assert "web.example.\t60\tIN\tA\t192.0.2.10" in text


def test_the_command_line(tmp_path, capsys) -> None:
    zone = tmp_path / "zone.txt"
    zone.write_text(ZONE, encoding="utf-8")

    assert main([str(zone), "web.example.", "A", "nope.example.", "A"]) == 0

    out = capsys.readouterr().out
    assert ";; status: NXDOMAIN" in out
    assert ";; upstream requests: 2" in out
