"""Agents (the people answering tickets) and the teams they belong to."""

from __future__ import annotations

from .. import audit
from ..context import Context
from ..errors import Conflict, ValidationError
from ..models import Agent, Team
from ..permissions import check_role, require
from ..textutil import is_handle


def create_agent(
    ctx: Context,
    agent_id: str,
    name: str,
    email: str,
    *,
    signature: str = "",
    role: str = "agent",
) -> Agent:
    require(ctx, "admin")
    check_role(role)
    if not is_handle(agent_id) or agent_id == audit.SYSTEM:
        raise ValidationError(f"bad agent id {agent_id!r}")
    if "@" not in email:
        raise ValidationError(f"not an email address: {email!r}")
    with ctx.store.transaction():
        if agent_id in ctx.store.agents:
            raise Conflict(f"agent {agent_id} already exists")
        agent = Agent(
            id=agent_id, name=name.strip(), email=email.strip(), signature=signature, role=role
        )
        ctx.store.agents[agent.id] = agent
        ctx.record("agent.created", agent.id, name=agent.name, role=role)
    return agent


def update_agent(
    ctx: Context,
    agent_id: str,
    *,
    name: str | None = None,
    email: str | None = None,
    signature: str | None = None,
) -> Agent:
    require(ctx, "admin")
    with ctx.store.transaction():
        agent = ctx.store.agent(agent_id)
        before = Agent.from_dict(agent.to_dict())
        if name is not None:
            agent.name = name.strip()
        if email is not None:
            if "@" not in email:
                raise ValidationError(f"not an email address: {email!r}")
            agent.email = email.strip()
        if signature is not None:
            agent.signature = signature
        diff = audit.changes(before, agent, ["name", "email", "signature"])
        if diff:
            ctx.record("agent.updated", agent.id, changes=diff)
    return agent


def set_active(ctx: Context, agent_id: str, active: bool) -> Agent:
    """Deactivating an agent hands their open tickets back to the queue."""
    require(ctx, "admin")
    with ctx.store.transaction():
        agent = ctx.store.agent(agent_id)
        if agent.active == active:
            return agent
        agent.active = active
        released = []
        if not active:
            for ticket in ctx.store.tickets.values():
                if ticket.assignee == agent.id and ticket.is_active:
                    ticket.assignee = None
                    ticket.updated_at = ctx.now()
                    released.append(ticket.id)
        ctx.record(
            "agent.activated" if active else "agent.deactivated", agent.id, released=released
        )
    return agent


def set_role(ctx: Context, agent_id: str, role: str) -> Agent:
    require(ctx, "admin", target=agent_id)
    check_role(role)
    with ctx.store.transaction():
        agent = ctx.store.agent(agent_id)
        if agent.role != role:
            old, agent.role = agent.role, role
            ctx.record("agent.role_changed", agent.id, **{"from": old, "to": role})
    return agent


def list_agents(ctx: Context, *, include_inactive: bool = False) -> list[Agent]:
    agents = sorted(ctx.store.agents.values(), key=lambda a: a.id)
    return [a for a in agents if a.active or include_inactive]


def create_team(ctx: Context, team_id: str, name: str) -> Team:
    require(ctx, "admin")
    if not is_handle(team_id):
        raise ValidationError(f"bad team id {team_id!r}")
    with ctx.store.transaction():
        if team_id in ctx.store.teams:
            raise Conflict(f"team {team_id} already exists")
        team = Team(id=team_id, name=name.strip() or team_id)
        ctx.store.teams[team.id] = team
        ctx.record("team.created", team.id, name=team.name)
    return team


def add_member(ctx: Context, team_id: str, agent_id: str) -> Team:
    require(ctx, "admin")
    with ctx.store.transaction():
        team = ctx.store.team(team_id)
        agent = ctx.store.agent(agent_id)
        if agent.id not in team.members:
            team.members.append(agent.id)
            agent.teams.append(team.id)
            ctx.record("team.member_added", team.id, agent=agent.id)
    return team


def remove_member(ctx: Context, team_id: str, agent_id: str) -> Team:
    require(ctx, "admin")
    with ctx.store.transaction():
        team = ctx.store.team(team_id)
        agent = ctx.store.agent(agent_id)
        if agent.id in team.members:
            team.members.remove(agent.id)
            agent.teams = [t for t in agent.teams if t != team.id]
            ctx.record("team.member_removed", team.id, agent=agent.id)
    return team


def list_teams(ctx: Context) -> list[Team]:
    return sorted(ctx.store.teams.values(), key=lambda t: t.id)
