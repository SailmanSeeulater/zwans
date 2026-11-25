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
