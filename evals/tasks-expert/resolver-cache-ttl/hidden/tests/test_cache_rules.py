"""The resolver against the README: lifetimes (chains, negative answers), TTLs that count
down, one fetch per question in flight, loops, serve-stale, and the upstream request count
that all of that implies."""

import asyncio
import random

import pytest
from reference import SERVFAIL, Reference, ZoneModel, plain

from relaydns import NOERROR, NXDOMAIN, ManualClock, Resolver, Zone
from relaydns.upstream import FakeUpstream

ZONE = """
$SOA example. 3600 ns1.example. hostmaster.example. 1 120
www.example.     300  CNAME  web.example.
web.example.      60  A      192.0.2.10
web.example.      60  A      192.0.2.11
short.example.    10  CNAME  web2.example.
web2.example.    300  A      192.0.2.20
lost.example.     20  CNAME  gone.example.
txt.example.     200  TXT    hello
loop1.example.   100  CNAME  loop2.example.
loop2.example.   100  CNAME  loop1.example.
self.example.    100  CNAME  self.example.
zero.example.      0  A      192.0.2.30
"""


class Rig:
    def __init__(self, text: str = ZONE, **options: int) -> None:
        self.upstream = FakeUpstream(Zone.parse(text), hold=True)
        self.clock = ManualClock(1000)
        self.resolver = Resolver(self.upstream, self.clock, **options)

    async def settle(self) -> None:
        for _ in range(20):
            await asyncio.sleep(0)

    async def ask_all(self, questions: list[tuple[str, str]]) -> list:
        """Ask everything at once, then let the upstream answer until all are done."""
        tasks = [asyncio.ensure_future(self.resolver.resolve(n, t)) for n, t in questions]
        for _ in range(40):
            await self.settle()
            if all(task.done() for task in tasks):
                return [task.result() for task in tasks]
            self.upstream.release()
        for task in tasks:
            task.cancel()
        raise AssertionError(f"still resolving after 40 upstream round trips: {questions}")

    async def ask(self, name: str, rtype: str = "A"):
        return (await self.ask_all([(name, rtype)]))[0]


def run(test):
    """Run an async test body in one event loop."""

    def wrapper(*args, **kwargs):
        asyncio.run(test(*args, **kwargs))

    wrapper.__name__ = test.__name__
    return wrapper


# -- lifetimes and TTLs


@run
async def test_ttls_count_down_while_cached() -> None:
    rig = Rig()
    assert (await rig.ask("txt.example.", "TXT")).ttls() == [200]

    rig.clock.advance(75)
    answer = await rig.ask("txt.example.", "TXT")

    assert answer.ttls() == [125]
    assert rig.upstream.requests == 1


@run
async def test_a_chain_lives_as_long_as_its_shortest_link() -> None:
    rig = Rig()
    first = await rig.ask("www.example.")
    assert first.ttls() == [60, 60, 60]

    rig.clock.advance(30)
    assert (await rig.ask("www.example.")).ttls() == [30, 30, 30]
    assert rig.upstream.requests == 2

    rig.clock.advance(30)
    await rig.ask("www.example.")
    assert rig.upstream.requests == 4


@run
async def test_a_short_lived_alias_expires_the_whole_chain() -> None:
    rig = Rig()
    assert (await rig.ask("short.example.")).ttls() == [10, 10]

    rig.clock.advance(10)
    rig.upstream.zone.replace("web2.example.", 300, "A", "192.0.2.99")
    answer = await rig.ask("short.example.")

    assert answer.final("A")[0].value == "192.0.2.99"


@run
async def test_names_along_a_chain_are_not_cached_on_their_own() -> None:
    rig = Rig()
    await rig.ask("www.example.")

    await rig.ask("web.example.")

    assert rig.upstream.requests == 3


@run
async def test_a_negative_answer_lives_for_the_smaller_of_the_soa_ttl_and_minimum() -> None:
    rig = Rig()
    missing = await rig.ask("nope.example.")
    assert missing.rcode == NXDOMAIN and missing.ttls() == [120]

    rig.clock.advance(100)
    assert (await rig.ask("nope.example.")).soa.ttl == 20
    rig.clock.advance(20)
    await rig.ask("nope.example.")
    assert rig.upstream.requests == 2

    low = Rig(ZONE.replace("example. 3600 ns1", "example. 45 ns1"))
    assert (await low.ask("nope.example.")).ttls() == [45]
    nodata = await low.ask("web.example.", "TXT")
    assert nodata.rcode == NOERROR and nodata.records == () and nodata.ttls() == [45]


@run
async def test_the_negative_ttl_is_capped() -> None:
    rig = Rig(max_negative_ttl=50)

    assert (await rig.ask("nope.example.")).ttls() == [50]


@run
async def test_a_chain_that_ends_in_nxdomain_lives_as_long_as_its_shortest_link() -> None:
    rig = Rig()

    answer = await rig.ask("lost.example.")

    assert answer.rcode == NXDOMAIN
    assert answer.ttls() == [20, 20]
    rig.clock.advance(20)
    await rig.ask("lost.example.")
    assert rig.upstream.requests == 4


@run
async def test_a_zero_lifetime_answer_replaces_the_cached_one_and_isnt_kept() -> None:
    rig = Rig()
    await rig.ask("web.example.")
    rig.clock.advance(60)
    rig.upstream.zone.replace("web.example.", 0, "A", "192.0.2.77")

    fresh = await rig.ask("web.example.")
    assert fresh.ttls() == [0]
    await rig.ask("web.example.")
    assert rig.upstream.requests == 3

    rig.upstream.down = True
    assert plain(await rig.ask("web.example.")) == SERVFAIL


# -- one fetch per question


@run
async def test_identical_queries_in_flight_share_one_fetch() -> None:
    rig = Rig()
    tasks = [asyncio.ensure_future(rig.resolver.resolve("WWW.example", "A")) for _ in range(6)]
    await rig.settle()
    assert rig.upstream.requests == 1

    rig.upstream.release()
    await rig.settle()
    assert rig.upstream.requests == 2
    rig.upstream.release()
    await rig.settle()

    answers = [task.result() for task in tasks]
    assert all(plain(answer) == plain(answers[0]) for answer in answers)
    assert answers[0].ttls() == [60, 60, 60]
    assert rig.upstream.requests == 2


@run
async def test_a_query_arriving_mid_fetch_joins_it() -> None:
    rig = Rig()
    first = asyncio.ensure_future(rig.resolver.resolve("www.example.", "A"))
    await rig.settle()
    rig.upstream.release()  # the CNAME arrives; the second step is now in flight
    await rig.settle()

    second = asyncio.ensure_future(rig.resolver.resolve("www.example.", "A"))
    await rig.settle()
    rig.upstream.release()
    await rig.settle()

    assert plain(first.result()) == plain(second.result())
    assert rig.upstream.requests == 2


@run
async def test_different_questions_are_fetched_separately() -> None:
    rig = Rig()

    await rig.ask_all([("www.example.", "A"), ("web.example.", "A"), ("www.example.", "TXT")])

    assert rig.upstream.requests == 5


@run
async def test_an_expired_answer_is_refetched_once_for_a_crowd() -> None:
    rig = Rig()
    await rig.ask("txt.example.", "TXT")
    rig.clock.advance(200)

    answers = await rig.ask_all([("txt.example.", "TXT")] * 8)

    assert rig.upstream.requests == 2
    assert {answer.ttls()[0] for answer in answers} == {200}


# -- loops


@run
async def test_a_loop_is_a_servfail_found_without_asking_again() -> None:
    rig = Rig()

    assert plain(await rig.ask("loop1.example.")) == SERVFAIL
    assert rig.upstream.requests == 2
    assert plain(await rig.ask("self.example.")) == SERVFAIL
    assert rig.upstream.requests == 3


@run
async def test_a_loop_doesnt_get_a_stale_answer() -> None:
    rig = Rig()
    await rig.ask("www.example.")
    rig.clock.advance(61)
    rig.upstream.zone.replace("web.example.", 60, "CNAME", "www.example.")

    assert plain(await rig.ask("www.example.")) == SERVFAIL


# -- serve-stale


@run
async def test_a_stale_answer_is_served_for_a_while_when_the_upstream_is_down() -> None:
    rig = Rig()
    await rig.ask("web.example.")  # fetched at 1000, expires at 1060
    rig.upstream.down = True

    rig.clock.set(1100)
    stale = await rig.ask("web.example.")
    assert stale.rcode == NOERROR and stale.ttls() == [30, 30]
    rig.clock.set(1119)
    assert (await rig.ask("web.example.")).ttls() == [30, 30]
    assert rig.upstream.requests == 3

    rig.clock.set(1120)
    assert plain(await rig.ask("web.example.")) == SERVFAIL

    rig.upstream.down = False
    assert (await rig.ask("web.example.")).ttls() == [60, 60]


@run
async def test_serve_stale_window_is_configurable_and_covers_negative_answers() -> None:
    rig = Rig(serve_stale=5)
    await rig.ask("nope.example.")  # expires at 1120
    rig.upstream.down = True

    rig.clock.set(1124)
    stale = await rig.ask("nope.example.")
    assert stale.rcode == NXDOMAIN and stale.ttls() == [30]
    rig.clock.set(1125)
    assert plain(await rig.ask("nope.example.")) == SERVFAIL


@run
async def test_a_failure_part_way_down_a_chain_stops_there() -> None:
    rig = Rig()
    rig.upstream.failing.add("web.example.")

    assert plain(await rig.ask("www.example.")) == SERVFAIL
    assert rig.upstream.requests == 2


# -- anything at all


NAMES = [f"n{index}.example." for index in range(10)]
TTLS = [0, 1, 5, 10, 10, 30, 60, 60, 300]
STEPS = [0, 0, 1, 2, 5, 9, 10, 20, 30, 59, 60, 61, 100, 301]


def random_entry(rng: random.Random) -> tuple[str, int, list[str]] | None:
    roll = rng.random()
    if roll < 0.3:
        return None
    if roll < 0.6:
        count = rng.randint(1, 2)
        return ("A", rng.choice(TTLS), [f"192.0.2.{rng.randint(1, 250)}" for _ in range(count)])
    if roll < 0.85:
        return ("CNAME", rng.choice(TTLS), [rng.choice(NAMES)])
    return ("TXT", rng.choice(TTLS), [f"t{rng.randint(1, 99)}"])


def reroll(rng: random.Random, zone: ZoneModel, name: str) -> None:
    entry = random_entry(rng)
    if entry is None:
        zone.names.pop(name, None)
    else:
        zone.names[name] = entry


def to_zone(model: ZoneModel) -> Zone:
    return Zone.parse(model.text())


@pytest.mark.parametrize("seed", range(150))
def test_any_sequence_of_queries_matches_the_readme(seed: int) -> None:
    asyncio.run(sequence(seed))


async def sequence(seed: int) -> None:
    rng = random.Random(seed)
    model = ZoneModel(soa_ttl=rng.choice([5, 30, 120, 3600]), soa_minimum=rng.choice([1, 20, 60, 600]))
    for name in NAMES[:8]:
        reroll(rng, model, name)
    options = {"max_negative_ttl": rng.choice([900, 45]), "serve_stale": rng.choice([60, 15])}
    rig = Rig(model.text(), **options)
    reference = Reference(**options)
    trail: list[str] = []

    for round_number in range(40):
        rig.clock.advance(rng.choice(STEPS))
        if rng.random() < 0.3:
            reroll(rng, model, rng.choice(NAMES[:8]))
            rig.upstream.zone = to_zone(model)
            trail.append(f"zone is now {model.names}")
        roll = rng.random()
        down, failing = False, set()
        if roll < 0.15:
            down = True
        elif roll < 0.3:
            failing = {rng.choice(NAMES)}
        rig.upstream.down, rig.upstream.failing = down, set(failing)

        questions = []
        for _ in range(rng.randint(1, 5)):
            rtype = rng.choices(["A", "TXT", "CNAME"], [70, 15, 15])[0]
            questions.append((rng.choice(NAMES), rtype))
        before = rig.upstream.requests
        got = [plain(answer) for answer in await rig.ask_all(questions)]
        spent = rig.upstream.requests - before

        now = rig.clock.now()
        want_by_question: dict[tuple[str, str], tuple] = {}
        want_spent = 0
        for question in dict.fromkeys(questions):
            want_by_question[question], requests = reference.ask(model, *question, now, down, failing)
            want_spent += requests
        trail.append(f"t={now} down={down} failing={failing} asked {questions}: {got}")
        for question, answer in zip(questions, got):
            want = want_by_question[question]
            assert answer == want, (
                f"seed {seed}, round {round_number}: {question} at t={now} gave {answer}, "
                f"should be {want}.\n" + "\n".join(trail[-12:])
            )
        assert spent == want_spent, (
            f"seed {seed}, round {round_number}: {spent} upstream requests for {questions} at "
            f"t={now}, should be {want_spent}.\n" + "\n".join(trail[-12:])
        )
