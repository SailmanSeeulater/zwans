"""Formatting for the command line."""

import json
import re
import sys
from decimal import Decimal, InvalidOperation

from orbit.errors import InvalidValue
from orbit.models import Contact, Deal
from orbit.reports.tables import money

MONEY = re.compile(r"^\d[\d,]*(\.\d{1,2})?$")


def parse_money(text: str) -> int:
    """ "1,200.50" -> 120050 cents."""
    text = text.strip()
    if not MONEY.match(text):
        raise InvalidValue(f"{text!r} is not an amount (like 1200 or 1,200.50).")
    try:
        return int(Decimal(text.replace(",", "")) * 100)
    except InvalidOperation:
        raise InvalidValue(f"{text!r} is not an amount.") from None


def say(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stdout)


def emit_json(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


def contact_line(contact: Contact) -> str:
    email = contact.primary_email or ""
    flags = "" if contact.active else "  (archived)"
    return f"{contact.id:<6} {contact.name:<28} {email}{flags}".rstrip()


def contact_card(contact: Contact, company_name: str = "") -> list[str]:
    lines = [f"{contact.name}  [{contact.id}]"]
    if contact.title or company_name:
        lines.append("  " + ", ".join(part for part in (contact.title, company_name) if part))
    for address in contact.emails:
        lines.append(f"  email   {address}")
    for number in contact.phones:
        lines.append(f"  phone   {number}")
    if contact.owner:
        lines.append(f"  owner   {contact.owner}")
    if contact.source:
        lines.append(f"  source  {contact.source}")
    if contact.tags:
        lines.append(f"  tags    {', '.join(contact.tags)}")
    for name, value in sorted(contact.fields.items()):
        shown = "; ".join(value) if isinstance(value, list) else value
        lines.append(f"  {name}: {shown}")
    if not contact.active:
        lines.append("  archived")
    return lines


def deal_line(deal: Deal) -> str:
    return f"{deal.id:<5} {deal.stage:<12} {money(deal.amount):>12}  {deal.title}"
