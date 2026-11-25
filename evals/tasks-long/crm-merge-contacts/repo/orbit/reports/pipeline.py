"""The sales pipeline: deals per stage, win rate, and how long deals sit in each stage."""

from collections import defaultdict
from dataclasses import dataclass

from orbit.clock import days_between
from orbit.models import OPEN_STAGES, STAGES, Deal
from orbit.reports.tables import money, render


@dataclass
class StageRow:
    stage: str
    deals: int
    amount: int


def pipeline(crm, owner: str | None = None) -> list[StageRow]:
    counts = {stage: [0, 0] for stage in STAGES}
    for row in crm.store.rows("deals"):
        if owner is not None and row.get("owner", "") != owner:
            continue
        counts[row["stage"]][0] += 1
        counts[row["stage"]][1] += row.get("amount", 0)
    return [StageRow(stage, n, amount) for stage, (n, amount) in counts.items()]


def win_rate(crm) -> float | None:
    won = lost = 0
    for row in crm.store.rows("deals"):
        won += row["stage"] == "won"
        lost += row["stage"] == "lost"
    return won / (won + lost) if won + lost else None


def open_value_by_owner(crm) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for row in crm.store.rows("deals"):
        if row["stage"] in OPEN_STAGES:
            totals[row.get("owner", "")] += row.get("amount", 0)
    return dict(sorted(totals.items()))


def stage_durations(crm, now: str) -> dict[str, float]:
    """Average days deals spent in each stage (a deal still in a stage counts up to now)."""
    spent: dict[str, list[float]] = defaultdict(list)
    for row in crm.store.rows("deals"):
        history = Deal.from_row(row).history()
        for current, following in zip(history, [*history[1:], None], strict=True):
            if following is None and current.stage not in OPEN_STAGES:
                continue
            until = following.at if following else now
            spent[current.stage].append(days_between(current.at, until))
    return {
        stage: round(sum(spent[stage]) / len(spent[stage]), 2) for stage in STAGES if spent[stage]
    }


def render_pipeline(rows: list[StageRow], rate: float | None) -> str:
    table = render(
        ["stage", "deals", "amount"],
        [[row.stage, row.deals, money(row.amount)] for row in rows],
        numeric={1, 2},
    )
    open_rows = [row for row in rows if row.stage in OPEN_STAGES]
    total = sum(row.amount for row in open_rows)
    footer = f"open: {sum(row.deals for row in open_rows)} deals, {money(total)}"
    if rate is not None:
        footer += f"; win rate {rate:.0%}"
    return f"{table}\n\n{footer}"
