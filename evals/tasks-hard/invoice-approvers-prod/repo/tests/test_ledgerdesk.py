from datetime import UTC, datetime
from decimal import Decimal

import pytest
from ledgerdesk.clock import parse_instant
from ledgerdesk.config import merge
from ledgerdesk.context import build_context
from ledgerdesk.policy.engine import Request, amount_eur, decide, who_can


@pytest.fixture(scope="module")
def dev():
    return build_context("dev")


def test_merge_replaces_lists_and_appends_plus_keys() -> None:
    base = {"a": [1], "b": {"c": [1], "d": 1}}
    assert merge(base, {"a": [2], "b": {"c+": [2]}}) == {"a": [2], "b": {"c": [1, 2], "d": 1}}
    assert base == {"a": [1], "b": {"c": [1], "d": 1}}


def test_naive_instants_are_utc() -> None:
    assert parse_instant("2025-11-14T09:00") == datetime(2025, 11, 14, 9, tzinfo=UTC)
    assert parse_instant("2025-11-14T10:00+01:00") == datetime(2025, 11, 14, 9, tzinfo=UTC)


def test_dev_values_invoices_at_the_invoice_date(dev) -> None:
    assert amount_eur(dev, dev.invoices.get("INV-2291")) == Decimal("10695.00")


def test_nested_groups(dev) -> None:
    assert "ngarcia" in dev.directory.members("finance-approvers")
    assert "obraun" not in dev.directory.members("finance-seniors")


def test_submitter_cannot_approve(dev) -> None:
    at = parse_instant("2025-11-05T10:00Z")
    invoice = dev.invoices.get("INV-2292")
    decision = decide(dev, Request(dev.directory.user("dlopez"), "invoice.approve", invoice, at))
    assert not decision.allowed


def test_who_can_lists_allowed_users_first(dev) -> None:
    decisions = who_can(dev, "invoice.approve", "INV-2290", parse_instant("2025-11-03T10:00Z"))
    allowed = [d.username for d in decisions if d.allowed]
    assert "jwagner" in allowed
    assert "fkrause" not in allowed  # submitted it
    assert "mweiss" not in allowed
