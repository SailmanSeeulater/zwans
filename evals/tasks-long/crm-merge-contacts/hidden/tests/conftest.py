import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from orbit import Crm
from orbit.cli.main import main
from orbit.clock import TickingClock

DATA = Path(__file__).parent / "data"
START = "2026-03-01T09:00:00Z"


def clock() -> TickingClock:
    return TickingClock(START, step=60)


@pytest.fixture
def crm() -> Crm:
    return Crm.memory(clock=clock())


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "crm.json"


@pytest.fixture
def v1_file(tmp_path: Path) -> Path:
    """A copy of a data file written by orbit 0.x."""
    target = tmp_path / "v1.json"
    shutil.copy(DATA / "v1.json", target)
    return target


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """cli("contact", "add", ...) -> (exit code, stdout, stderr), on a data file of its own."""
    target = tmp_path / "cli.json"
    monkeypatch.setenv("ORBIT_NOW", START)
    monkeypatch.delenv("ORBIT_DB", raising=False)

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--db", str(target), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = target
    return run


def seed(crm: Crm) -> dict[str, str]:
    """A few companies, contacts, deals and activities; returns their ids by nickname."""
    engines = crm.add_company("Analytical Engines", "analytical.example")
    navy = crm.add_company("US Navy", "navy.example")
    ada = crm.add_contact(
        "Ada",
        "Lovelace",
        emails=["ada@analytical.example"],
        phones=["+44 20 7946 0000"],
        company_id=engines.id,
        owner="sam",
        source="conference",
        tags=["vip"],
    )
    grace = crm.add_contact(
        "Grace", "Hopper", emails=["grace@navy.example"], company_id=navy.id, owner="kim"
    )
    charles = crm.add_contact("Charles", "Babbage", emails=["cb@analytical.example"], owner="sam")
    crm.add_note(ada.id, "Wants a quote for the difference engine")
    crm.log_email(ada.id, "Quote attached")
    crm.add_task(ada.id, "Call back about the quote", due="2026-03-05")
    engine = crm.add_deal(
        "Difference engine", 1_200_000, [ada.id, charles.id], company_id=engines.id, owner="sam"
    )
    compiler = crm.add_deal(
        "Compiler licence", 450_000, [grace.id], company_id=navy.id, owner="kim"
    )
    crm.move_deal(engine.id, "qualified", contact_id=ada.id)
    return {
        "engines": engines.id,
        "navy": navy.id,
        "ada": ada.id,
        "grace": grace.id,
        "charles": charles.id,
        "engine": engine.id,
        "compiler": compiler.id,
    }


def world(crm: Crm) -> dict[str, str]:
    """Ada (A) and her duplicate Augusta (B), with everything that can point at a contact.

    A: c1, B: c2, Charles: c3, Grace: c4, Grace's twin: c5.
    d1 has contacts [B, Charles, A]; d2 [B, Charles], moved to qualified after talking to
    B; d3 [Grace]. The Navy's primary contact is B.
    """
    engines = crm.add_company("Analytical Engines", "analytical.example")
    navy = crm.add_company("US Navy", "navy.example")
    crm.define_field("size", "choice", choices=["s", "m", "l"])
    crm.define_field("seats", "number")
    crm.define_field("renewal", "date")
    crm.define_field("nickname")
    crm.define_field("interests", "multi", choices=["engines", "looms", "cards", "poetry"])

    a = crm.add_contact(
        "Ada",
        "Lovelace",
        emails=["ada@analytical.example"],
        phones=["+44 20 7946 0000"],
        company_id=engines.id,
        owner="sam",
        source="conference",
        tags=["vip"],
    )
    b = crm.add_contact(
        "Augusta",
        "King",
        emails=["ADA@analytical.example", "countess@home.example"],
        phones=["+44 (20) 7946-0000", "+44 1632 960111"],
        company_id=navy.id,
        title="Countess",
        owner="kim",
        source="web",
        tags=["looms", "vip"],
    )
    charles = crm.add_contact("Charles", "Babbage", emails=["cb@analytical.example"], owner="sam")
    grace = crm.add_contact("Grace", "Hopper", emails=["grace@navy.example"], owner="kim")
    twin = crm.add_contact("grace", "HOPPER", owner="kim")

    crm.set_field(a.id, "size", "m")
    crm.set_field(a.id, "seats", 3)
    crm.set_field(a.id, "interests", ["engines", "poetry"])
    crm.set_field(b.id, "size", "l")
    crm.set_field(b.id, "seats", 5)
    crm.set_field(b.id, "renewal", "2026-09-01")
    crm.set_field(b.id, "nickname", "Enchantress")
    crm.set_field(b.id, "interests", ["looms", "engines", "cards"])

    crm.add_note(a.id, "Wants a quote for the difference engine")
    crm.log_email(a.id, "Quote attached")
    crm.add_task(a.id, "Call back about the quote", due="2026-03-05")
    crm.add_note(b.id, "Collects punched cards")
    crm.add_task(b.id, "Send the loom catalogue", due="2026-03-02")
    crm.log_email(b.id, "Loom pattern samples", direction="in")

    d1 = crm.add_deal("Difference engine", 1_200_000, [b.id, charles.id, a.id], owner="sam")
    d2 = crm.add_deal("Jacquard loom", 300_000, [b.id, charles.id], owner="kim")
    d3 = crm.add_deal("Compiler licence", 450_000, [grace.id], owner="kim")
    crm.move_deal(d2.id, "qualified", contact_id=b.id)
    crm.move_deal(d1.id, "proposal", contact_id=charles.id)
    crm.set_primary_contact(navy.id, b.id)
    return {
        "engines": engines.id,
        "navy": navy.id,
        "a": a.id,
        "b": b.id,
        "charles": charles.id,
        "grace": grace.id,
        "twin": twin.id,
        "d1": d1.id,
        "d2": d2.id,
        "d3": d3.id,
    }
