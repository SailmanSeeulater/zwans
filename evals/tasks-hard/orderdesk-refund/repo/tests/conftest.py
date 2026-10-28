from collections.abc import Callable
from pathlib import Path

import pytest
from orderdesk import App, open_app
from orderdesk.cli import main
from orderdesk.events import Line
from orderdesk.handlers.pay import PayOrder
from orderdesk.handlers.place import PlaceOrder
from orderdesk.permissions import Actor

CLERK = Actor("carla", "clerk")
MANAGER = Actor("mo", "manager")
AUDITOR = Actor("ada", "auditor")


class Clock:
    def __init__(self, at: str = "2026-03-01T09:00:00Z") -> None:
        self.at = at

    def __call__(self) -> str:
        return self.at


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def app(clock: Clock) -> App:
    return open_app(None, clock=clock)


def place(app: App, customer: str = "alice", *lines: Line) -> str:
    order_id = app.desk.next_order_id()
    lines = lines or (Line("MUG-01", 2, 950), Line("TEA-07", 1, 1100))
    app.desk.execute(PlaceOrder(order_id, customer, f"{customer}@example.com", lines), CLERK)
    return order_id


def place_and_pay(app: App, customer: str = "alice", *lines: Line) -> str:
    order_id = place(app, customer, *lines)
    app.desk.execute(PayOrder(order_id, app.desk.state(order_id).total_cents, "card"), CLERK)
    return order_id


@pytest.fixture
def cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> Callable:
    """Run the CLI on a data folder of its own: cli("--role", "manager", "report").

    Returns (exit code, stdout, stderr). cli.at("2026-03-02T10:00:00Z") moves the clock.
    """
    data = tmp_path / "data"
    monkeypatch.setenv("ORDERDESK_NOW", "2026-03-01T09:00:00Z")

    def run(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(["--data", str(data), *argv])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    run.at = lambda when: monkeypatch.setenv("ORDERDESK_NOW", when)
    run.data = data
    return run
