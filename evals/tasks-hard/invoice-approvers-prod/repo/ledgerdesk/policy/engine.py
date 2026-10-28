"""The policy engine: may this user do this to this invoice, right now?

A user may act when, at the instant in question:

1. the user is active;
2. they hold at least one role granting the permission, directly (group bindings),
   through a delegation in force (ledgerdesk.policy.delegation) or from a plugin;
3. for `invoice.approve`, one of those roles has a limit at least as large as the
   invoice's total in euros (see `amount_eur`), or has no limit at all;
4. no enabled plugin vetoes the request.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ledgerdesk.context import Context
from ledgerdesk.directory import User
from ledgerdesk.invoices import Invoice
from ledgerdesk.policy.delegation import delegations_to
from ledgerdesk.policy.roles import direct_roles


@dataclass(frozen=True)
class Holding:
    role: str
    source: str  # "binding", "delegation" or "plugin"
    detail: str = ""  # for a delegation, the delegator; for a plugin, its name


@dataclass(frozen=True)
class Request:
    user: User
    permission: str
    invoice: Invoice
    at: datetime


@dataclass
class Decision:
    username: str
    allowed: bool
    reason: str = ""
    holdings: list[Holding] = field(default_factory=list)

    @property
    def via(self) -> str:
        """How the user came to be allowed, for display: '' when through their own roles."""
        sources = {h.source for h in self.holdings}
        if "binding" in sources:
            return ""
        if "delegation" in sources:
            return "via " + ", ".join(
                sorted({h.detail for h in self.holdings if h.source == "delegation"})
            )
        return "via plugin " + ", ".join(sorted({h.detail for h in self.holdings}))


def valuation_date(ctx: Context, invoice: Invoice) -> date:
    basis = ctx.config.get("money", {}).get("valuation", "invoice_date")
    if basis == "invoice_date":
        return invoice.invoice_date
    if basis == "received":
        return invoice.received
    raise ValueError(f"unknown money.valuation {basis!r}")


def amount_eur(ctx: Context, invoice: Invoice) -> Decimal:
    """The invoice total in euros, at the rate for the configured valuation date."""
    return ctx.rates.to_eur(invoice.total, valuation_date(ctx, invoice))


def holdings(ctx: Context, user: User, at: datetime) -> list[Holding]:
    """Every role `user` holds at `at`, and where it comes from."""
    held = [
        Holding(role, "binding")
        for role in direct_roles(user.username, ctx.bindings, ctx.directory)
    ]
    strict = ctx.feature("strict_delegation")
    for delegation in delegations_to(user.username, ctx.delegations, at, ctx.directory, strict):
        for role in direct_roles(delegation.delegator, ctx.bindings, ctx.directory):
            if ctx.roles.get(role).permissions & delegation.permissions:
                held.append(Holding(role, "delegation", delegation.delegator))
    for plugin in ctx.plugins:
        for role in plugin.grants(ctx, user, at):
            held.append(Holding(role, "plugin", plugin.name))
    return held


def decide(ctx: Context, request: Request) -> Decision:
    user = request.user
    decision = Decision(user.username, allowed=False)
    if not user.active:
        decision.reason = "deactivated"
        return decision
    relevant = [
        h
        for h in holdings(ctx, user, request.at)
        if request.permission in ctx.roles.get(h.role).permissions
    ]
    if not relevant:
        decision.reason = f"no role grants {request.permission}"
        return decision
    if request.permission == "invoice.approve":
        amount = amount_eur(ctx, request.invoice)
        limits = [ctx.roles.get(h.role).limit_eur for h in relevant]
        if None not in limits and max(limits) < amount:  # type: ignore[type-var]
            decision.reason = f"limit {max(limits):,} EUR is below {amount:,} EUR"  # type: ignore[type-var]
            decision.holdings = relevant
            return decision
        relevant = [
            h
            for h in relevant
            if ctx.roles.get(h.role).limit_eur is None or ctx.roles.get(h.role).limit_eur >= amount
        ]
    for plugin in ctx.plugins:
        veto = plugin.check(ctx, request)
        if veto:
            decision.reason = f"{plugin.name}: {veto}"
            decision.holdings = relevant
            return decision
    decision.allowed = True
    decision.holdings = relevant
    return decision


def who_can(ctx: Context, permission: str, invoice_id: str, at: datetime) -> list[Decision]:
    """A decision for every active user, allowed ones first, each group sorted by username."""
    invoice = ctx.invoices.get(invoice_id)
    decisions = [
        decide(ctx, Request(user, permission, invoice, at)) for user in ctx.directory.users()
    ]
    return sorted(decisions, key=lambda d: (not d.allowed, d.username))
