"""orbit deal ..."""

from orbit.cli.output import deal_line, emit_json, parse_money, say
from orbit.models import STAGES
from orbit.payloads import deal_payload
from orbit.reports.tables import money


def register(commands) -> None:
    deal = commands.add_parser("deal", help="deals and the pipeline")
    sub = deal.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add")
    add.add_argument("title")
    add.add_argument("--amount", default="0")
    add.add_argument("--contact", action="append", default=[])
    add.add_argument("--company")
    add.add_argument("--owner", default="")
    add.add_argument("--stage", default="lead", choices=STAGES)
    add.set_defaults(handler=add_deal)

    move = sub.add_parser("move")
    move.add_argument("id")
    move.add_argument("stage", choices=STAGES)
    move.add_argument("--contact", help="the contact this move came out of")
    move.set_defaults(handler=move_deal)

    show = sub.add_parser("show")
    show.add_argument("id")
    show.set_defaults(handler=show_deal)

    listing = sub.add_parser("list")
    listing.add_argument("--stage", choices=STAGES)
    listing.add_argument("--open", action="store_true")
    listing.add_argument("--contact")
    listing.set_defaults(handler=list_deals)

    link = sub.add_parser("link")
    link.add_argument("id")
    link.add_argument("contact")
    link.set_defaults(handler=link_contact)

    unlink = sub.add_parser("unlink")
    unlink.add_argument("id")
    unlink.add_argument("contact")
    unlink.set_defaults(handler=unlink_contact)

    amount = sub.add_parser("amount")
    amount.add_argument("id")
    amount.add_argument("amount")
    amount.set_defaults(handler=set_amount)


def add_deal(crm, args) -> bool:
    with crm.operation("add deal"):
        company_id = crm.companies.find_or_create(args.company).id if args.company else None
        deal = crm.deals.create(
            args.title,
            parse_money(args.amount),
            args.contact,
            company_id=company_id,
            owner=args.owner,
            stage=args.stage,
        )
    say(f"Added {deal.id} {deal.title}")
    return True


def move_deal(crm, args) -> bool:
    deal = crm.move_deal(args.id, args.stage, args.contact)
    say(f"{deal.id} {deal.title} is now at {deal.stage}")
    return True


def show_deal(crm, args) -> bool:
    deal = crm.deal(args.id)
    if args.json:
        emit_json({**deal_payload(deal), "stage_history": deal.stage_history})
        return False
    say(f"{deal.title}  [{deal.id}]", f"  {deal.stage}, {money(deal.amount)}")
    if deal.owner:
        say(f"  owner {deal.owner}")
    for contact_id in deal.contact_ids:
        say(f"  contact {contact_id} {crm.contact(contact_id).name}")
    for change in deal.history():
        who = f"  (after talking to {change.contact_id})" if change.contact_id else ""
        say(f"  {change.at}  {change.stage}{who}")
    return False


def list_deals(crm, args) -> bool:
    deals = crm.list_deals(args.stage, args.open)
    if args.contact:
        contact = crm.contact(args.contact)
        deals = [deal for deal in deals if contact.id in deal.contact_ids]
    if args.json:
        emit_json([deal_payload(deal) for deal in deals])
    else:
        say(*(deal_line(deal) for deal in deals))
    return False


def link_contact(crm, args) -> bool:
    deal = crm.add_deal_contact(args.id, args.contact)
    say(f"{deal.id} contacts: {', '.join(deal.contact_ids)}")
    return True


def unlink_contact(crm, args) -> bool:
    deal = crm.remove_deal_contact(args.id, args.contact)
    say(f"{deal.id} contacts: {', '.join(deal.contact_ids) or 'none'}")
    return True


def set_amount(crm, args) -> bool:
    deal = crm.update_deal(args.id, amount=parse_money(args.amount))
    say(f"{deal.id} {deal.title}: {money(deal.amount)}")
    return True
