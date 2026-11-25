import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from deskline import Desk
from deskline.cli.main import main
from deskline.clock import SteppingClock
from deskline.services import agents, customers, queues

DATA = Path(__file__).parent / "data"


@pytest.fixture
def clock() -> SteppingClock:
    return SteppingClock("2026-03-02T09:00:00Z")


@pytest.fixture
def desk(clock: SteppingClock) -> Desk:
    return Desk.memory(clock)


@pytest.fixture
def ctx(desk: Desk):
    return desk.system


def seed(desk: Desk) -> dict:
    """Two agents in a billing team, a billing queue, two customers."""
    ctx = desk.system
    agents.create_agent(ctx, "maria", "Maria Lopez", "maria@ourdesk.example", signature="Maria")
    agents.create_agent(ctx, "tom", "Tom Berg", "tom@ourdesk.example")
    agents.create_team(ctx, "money", "Billing people")
    agents.add_member(ctx, "money", "maria")
    agents.add_member(ctx, "money", "tom")
    queues.create_queue(ctx, "billing", "Billing", team="money", keywords=["invoice", "refund"])
    jane = customers.create(
        ctx,
        "Jane Doe",
        email="jane@example.org",
        phone="+1 555 0101",
        address="12 Elm Street, Springfield",
        organization="Example Org",
    )
    bob = customers.create(ctx, "Bob Stone", email="bob@stone.example", phone="+44 20 7946 0000")
    return {"jane": jane, "bob": bob}


@pytest.fixture
def seeded(desk: Desk) -> dict:
    return seed(desk)


@pytest.fixture
def legacy_file(tmp_path: Path) -> Path:
    path = tmp_path / "legacy.json"
    shutil.copy(DATA / "legacy_v1.json", path)
    return path


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """cli("ticket", "show", "T-1") -> (exit code, stdout, stderr) on a helpdesk of its own."""
    path = tmp_path / "desk.json"
    monkeypatch.setenv("DESKLINE_NOW", "2026-03-02T09:00:00Z")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--db", str(path), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.path = path
    assert run("init")[0] == 0
    return run


# -- roles ------------------------------------------------------------------------------

JANE_EMAIL = "jane@example.org"
JANE_PHONE = "+1 555 0101"
JANE_ADDRESS = "12 Elm Street, Springfield"
BOB_EMAIL = "bob@stone.example"
BOB_PHONE = "+44 20 7946 0000"
CONTACTS = (JANE_EMAIL, JANE_PHONE, JANE_ADDRESS, BOB_EMAIL, BOB_PHONE)
REDACTED = "[redacted]"

ROLE_OF = {"vic": "viewer", "ana": "agent", "al": "agent", "lou": "lead", "ada": "admin"}


def leaks(value) -> list[str]:
    """The contact details that appear anywhere in ``value`` (a str, or anything repr-able)."""
    text = value if isinstance(value, str) else repr(value)
    return [c for c in CONTACTS if c in text]


def staff(desk: Desk) -> dict:
    """A viewer, two agents, a lead and an admin; a billing team and queue; customers.

    jane has every contact detail, bob has no address, kim has none at all.
    """
    ctx = desk.system
    for agent_id, role in ROLE_OF.items():
        agents.create_agent(
            ctx, agent_id, agent_id.title(), f"{agent_id}@ourdesk.example", role=role
        )
    agents.create_team(ctx, "money", "Billing people")
    agents.add_member(ctx, "money", "ana")
    agents.add_member(ctx, "money", "lou")
    queues.create_queue(ctx, "billing", "Billing", team="money", keywords=["invoice", "refund"])
    jane = customers.create(
        ctx,
        "Jane Doe",
        email=JANE_EMAIL,
        phone=JANE_PHONE,
        address=JANE_ADDRESS,
        organization="Example Org",
    )
    bob = customers.create(ctx, "Bob Stone", email=BOB_EMAIL, phone=BOB_PHONE)
    kim = customers.create(ctx, "Kim Quiet")
    return {"jane": jane, "bob": bob, "kim": kim}


@pytest.fixture
def people(desk: Desk) -> dict:
    return staff(desk)


@pytest.fixture
def as_(desk: Desk) -> Callable:
    """as_("ana") -> a context acting as ana."""
    return lambda agent_id: desk.context(agent_id)
