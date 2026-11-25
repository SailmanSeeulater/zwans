"""Satisfaction surveys: one per solved ticket, answered with a rating from 1 to 5."""

from __future__ import annotations

import hashlib

from .. import notify
from ..context import Context
from ..errors import Conflict, NotFound, ValidationError
from ..models import Survey, Ticket


def _token(ticket_id: str, at: str) -> str:
    return hashlib.sha256(f"survey:{ticket_id}:{at}".encode()).hexdigest()[:12]


def for_ticket(ctx: Context, ticket_id: str) -> Survey | None:
    for survey in ctx.store.surveys.values():
        if survey.ticket_id == ticket_id:
            return survey
    return None


def on_solved(ctx: Context, ticket: Ticket) -> Survey | None:
    """Send a survey the first time a ticket is solved, if the desk wants surveys."""
    if not ctx.setting("survey_on_solve"):
        return None
    if for_ticket(ctx, ticket.id) is not None:
        return None
    customer = ctx.store.customers.get(ticket.customer_id)
    if customer is None or not customer.email:
        return None
    now = ctx.now()
    survey = Survey(
        id=ctx.store.next_id("survey", "S"),
        ticket_id=ticket.id,
        token=_token(ticket.id, now),
        sent_at=now,
    )
    ctx.store.surveys[survey.id] = survey
    ctx.record("survey.sent", ticket.id, survey=survey.id)
    notify.survey_sent(ctx, ticket, survey)
    return survey


def respond(ctx: Context, token: str, rating: int, remark: str = "") -> Survey:
    if not isinstance(rating, int) or not 1 <= rating <= 5:
        raise ValidationError("a rating is a whole number from 1 to 5")
    with ctx.store.transaction():
        for survey in ctx.store.surveys.values():
            if survey.token == token:
                break
        else:
            raise NotFound("survey", token)
        if survey.answered_at is not None:
            raise Conflict("this survey has already been answered")
        survey.rating = rating
        survey.remark = remark.strip()
        survey.answered_at = ctx.now()
        ctx.record("survey.answered", survey.ticket_id, survey=survey.id, rating=rating)
    return survey


def answered(ctx: Context, since: str | None = None) -> list[Survey]:
    out = [
        s
        for s in ctx.store.surveys.values()
        if s.rating is not None and (since is None or (s.answered_at or "") >= since)
    ]
    return sorted(out, key=lambda s: s.answered_at or "")
