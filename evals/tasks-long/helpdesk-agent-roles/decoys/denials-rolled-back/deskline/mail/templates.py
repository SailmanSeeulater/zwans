"""Email templates.

A tiny template language, enough for helpdesk mail:

- ``{{ customer.name }}`` inserts a value (missing values insert nothing);
- ``{{ ticket.subject | upper }}`` applies a filter (upper, lower, title, date, indent);
- ``{% if customer.phone %}...{% endif %}`` keeps a block when the value is non-empty;
- ``{% for c in comments %}...{% endfor %}`` repeats a block for each item.

Each built-in template has a subject, a body and an audience: ``customer`` templates are
mailed to the requester, ``agent`` templates to agents.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import config
from ..errors import NotFound, TemplateError
from ..models import Comment, Ticket
from ..redact import value
from ..store import Store


@dataclass(frozen=True)
class Template:
    name: str
    audience: str
    subject: str
    body: str


BUILTIN: dict[str, Template] = {}


def _define(name: str, audience: str, subject: str, body: str) -> None:
    BUILTIN[name] = Template(name, audience, subject, body.strip("\n") + "\n")


_define(
    "customer_ack",
    "customer",
    "[{{ ticket.id }}] {{ ticket.subject }}",
    """
Hello {{ customer.name }},

Thanks for getting in touch with {{ desk.name }}. We have your request and will reply
as soon as we can. To add anything, just reply to this email.

Your reference is {{ ticket.id }}.
""",
)
_define(
    "customer_reply",
    "customer",
    "Re: [{{ ticket.id }}] {{ ticket.subject }}",
    """
Hello {{ customer.name }},

{{ comment.body }}

{% if assignee.signature %}{{ assignee.signature }}{% endif %}{% if assignee.name %}
-- {{ assignee.name }}, {{ desk.name }}{% endif %}
""",
)
_define(
    "survey_request",
    "customer",
    "How did we do? [{{ ticket.id }}]",
    """
Hello {{ customer.name }},

Your request "{{ ticket.subject }}" has been solved. Would you rate our help from 1 to 5?
Reply with your rating, or use this code on our site: {{ survey.token }}

Thank you,
{{ desk.name }}
""",
)
_define(
    "agent_new_ticket",
    "agent",
    "New ticket {{ ticket.id }} in {{ queue.name }}: {{ ticket.subject }}",
    """
A new {{ ticket.priority }} ticket arrived in {{ queue.name }}.

From: {{ customer.name }} <{{ customer.email }}>
{% if customer.phone %}Phone: {{ customer.phone }}
{% endif %}{% if customer.organization %}Organization: {{ customer.organization }}
{% endif %}
{{ ticket.first_message | indent }}
""",
)
_define(
    "agent_assigned",
    "agent",
    "{{ ticket.id }} is assigned to you: {{ ticket.subject }}",
    """
Hi {{ recipient.name }},

{{ ticket.id }} ({{ ticket.priority }}, {{ ticket.status }}) is now assigned to you.

Requester: {{ customer.name }} <{{ customer.email }}>
{% if customer.phone %}Phone: {{ customer.phone }}
{% endif %}{% if customer.address %}Address: {{ customer.address }}
{% endif %}
Latest message:
{{ ticket.last_public | indent }}
""",
)
_define(
    "agent_customer_replied",
    "agent",
    "Customer replied on {{ ticket.id }}: {{ ticket.subject }}",
    """
Hi {{ recipient.name }},

{{ customer.name }} <{{ comment.from_address }}> wrote on {{ comment.created_at | date }}:

{{ comment.body | indent }}
""",
)
_define(
    "agent_sla_breach",
    "agent",
    "SLA breached on {{ ticket.id }} ({{ breach.target }})",
    """
Hi {{ recipient.name }},

The {{ breach.target }} target for {{ ticket.id }} ({{ ticket.priority }}) was due at
{{ breach.due | date }} and has passed.

Requester: {{ customer.name }}
Email: {{ customer.email }}
Phone: {{ customer.phone }}
""",
)


# -- rendering --------------------------------------------------------------------------

_TOKEN = re.compile(r"({{.*?}}|{%.*?%})", re.S)


def _lookup(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _indent(text: str) -> str:
    return "\n".join("    " + line if line else line for line in str(text).splitlines())


FILTERS = {
    "upper": lambda v: str(v).upper(),
    "lower": lambda v: str(v).lower(),
    "title": lambda v: str(v).title(),
    "date": lambda v: str(v).replace("T", " ").rstrip("Z")[:16],
    "indent": _indent,
}


def _value(expression: str, context: dict[str, Any]) -> str:
    parts = [p.strip() for p in expression.split("|")]
    value = _lookup(context, parts[0])
    if value is None:
        return ""
    for name in parts[1:]:
        try:
            value = FILTERS[name](value)
        except KeyError:
            raise TemplateError(f"unknown filter {name!r}") from None
    return str(value)


def _parse(tokens: list[str], pos: int, until: tuple[str, ...]) -> tuple[list, int, str]:
    nodes: list = []
    while pos < len(tokens):
        token = tokens[pos]
        if token.startswith("{%"):
            words = token[2:-2].split()
            if not words:
                raise TemplateError("empty tag")
            if words[0] in until:
                return nodes, pos + 1, words[0]
            if words[0] == "if" and len(words) == 2:
                body, pos, _ = _parse(tokens, pos + 1, ("endif",))
                nodes.append(("if", words[1], body))
                continue
            if words[0] == "for" and len(words) == 4 and words[2] == "in":
                body, pos, _ = _parse(tokens, pos + 1, ("endfor",))
                nodes.append(("for", (words[1], words[3]), body))
                continue
            raise TemplateError(f"bad tag {token!r}")
        if token.startswith("{{"):
            nodes.append(("value", token[2:-2].strip(), None))
        elif token:
            nodes.append(("text", token, None))
        pos += 1
    if until:
        raise TemplateError(f"missing {{% {until[0]} %}}")
    return nodes, pos, ""


def _emit(nodes: list, context: dict[str, Any]) -> str:
    out = []
    for kind, arg, body in nodes:
        if kind == "text":
            out.append(arg)
        elif kind == "value":
            out.append(_value(arg, context))
        elif kind == "if":
            if _lookup(context, arg):
                out.append(_emit(body, context))
        elif kind == "for":
            name, source = arg
            for item in _lookup(context, source) or []:
                out.append(_emit(body, {**context, name: item}))
    return "".join(out)


def render_text(source: str, context: dict[str, Any]) -> str:
    tokens = _TOKEN.split(source)
    nodes, _, _ = _parse(tokens, 0, ())
    return _emit(nodes, context)


def get(name: str) -> Template:
    try:
        return BUILTIN[name]
    except KeyError:
        raise NotFound("template", name) from None


def render(name: str, context: dict[str, Any]) -> tuple[str, str]:
    template = get(name)
    subject = " ".join(render_text(template.subject, context).split())
    return subject, render_text(template.body, context)


# -- contexts ---------------------------------------------------------------------------


def customer_fields(store: Store, customer_id: str, *, hide: bool = False) -> dict[str, Any]:
    customer = store.customers.get(customer_id)
    if customer is None:
        return {"id": customer_id, "name": "(unknown)"}
    return {
        "id": customer.id,
        "name": customer.name,
        "email": value(customer.email, hide),
        "phone": value(customer.phone, hide),
        "address": value(customer.address, hide),
        "organization": customer.organization,
    }


def _comment(comment: Comment, hide: bool) -> dict[str, Any]:
    data = comment.to_dict()
    data["from_address"] = value(comment.from_address, hide)
    return data


def ticket_context(
    store: Store,
    ticket: Ticket,
    *,
    comment: Comment | None = None,
    extra: dict[str, Any] | None = None,
    hide: bool = False,
) -> dict[str, Any]:
    """What templates can refer to. ``hide`` redacts the requester's contact details."""
    public = ticket.public_comments()
    queue = store.queues.get(ticket.queue)
    assignee = store.agents.get(ticket.assignee) if ticket.assignee else None
    context: dict[str, Any] = {
        "desk": {
            "name": config.get(store.settings, "desk_name"),
            "address": config.get(store.settings, "support_address"),
        },
        "ticket": {
            "id": ticket.id,
            "subject": ticket.subject,
            "status": ticket.status,
            "priority": ticket.priority,
            "queue": ticket.queue,
            "tags": ", ".join(ticket.tags),
            "created_at": ticket.created_at,
            "first_message": public[0].body if public else "",
            "last_public": public[-1].body if public else "",
        },
        "queue": {"id": ticket.queue, "name": queue.name if queue else ticket.queue},
        "customer": customer_fields(store, ticket.customer_id, hide=hide),
        "assignee": (
            {"id": assignee.id, "name": assignee.name, "signature": assignee.signature}
            if assignee
            else {}
        ),
        "comments": [_comment(c, hide) for c in public],
    }
    if comment is not None:
        context["comment"] = _comment(comment, hide)
    if extra:
        context.update(extra)
    return context
