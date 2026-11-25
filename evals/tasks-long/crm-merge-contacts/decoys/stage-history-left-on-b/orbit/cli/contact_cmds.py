"""orbit contact ..., company ..., tag/untag/tags/tagged, field ..., search, dupes."""

from orbit.cli.output import contact_card, contact_line, emit_json, say


def register(commands) -> None:
    contact = commands.add_parser("contact", help="add, show, change and list contacts")
    sub = contact.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add")
    add.add_argument("first_name")
    add.add_argument("last_name", nargs="?", default="")
    add.add_argument("--email", action="append", default=[])
    add.add_argument("--phone", action="append", default=[])
    add.add_argument("--company")
    add.add_argument("--title", default="")
    add.add_argument("--owner")
    add.add_argument("--source", default="")
    add.add_argument("--tag", action="append", default=[])
    add.set_defaults(handler=add_contact)

    show = sub.add_parser("show")
    show.add_argument("id")
    show.set_defaults(handler=show_contact)

    listing = sub.add_parser("list")
    listing.add_argument("--all", action="store_true", help="include archived contacts")
    listing.add_argument("--company")
    listing.set_defaults(handler=list_contacts)

    edit = sub.add_parser("edit")
    edit.add_argument("id")
    edit.add_argument("--first")
    edit.add_argument("--last")
    edit.add_argument("--title")
    edit.add_argument("--owner")
    edit.add_argument("--source")
    edit.add_argument("--company")
    edit.add_argument("--add-email", action="append", default=[])
    edit.add_argument("--add-phone", action="append", default=[])
    edit.set_defaults(handler=edit_contact)

    for name, handler in (("archive", archive_contact), ("unarchive", unarchive_contact)):
        parser = sub.add_parser(name)
        parser.add_argument("id")
        parser.set_defaults(handler=handler)

    company = commands.add_parser("company", help="companies")
    csub = company.add_subparsers(dest="action", required=True)
    cadd = csub.add_parser("add")
    cadd.add_argument("name")
    cadd.add_argument("--domain", default="")
    cadd.set_defaults(handler=add_company)
    csub.add_parser("list").set_defaults(handler=list_companies)
    rename = csub.add_parser("rename")
    rename.add_argument("id")
    rename.add_argument("name")
    rename.set_defaults(handler=rename_company)
    primary = csub.add_parser("primary")
    primary.add_argument("id")
    primary.add_argument("contact", nargs="?")
    primary.set_defaults(handler=set_primary)

    tag = commands.add_parser("tag", help="tag a contact")
    tag.add_argument("id")
    tag.add_argument("tags", nargs="+")
    tag.set_defaults(handler=tag_contact)
    untag = commands.add_parser("untag", help="remove tags from a contact")
    untag.add_argument("id")
    untag.add_argument("tags", nargs="+")
    untag.set_defaults(handler=untag_contact)
    commands.add_parser("tags", help="every tag and how many contacts have it").set_defaults(
        handler=list_tags
    )
    tagged = commands.add_parser("tagged", help="contacts with a tag")
    tagged.add_argument("tag")
    tagged.set_defaults(handler=list_tagged)

    field = commands.add_parser("field", help="custom fields")
    fsub = field.add_subparsers(dest="action", required=True)
    define = fsub.add_parser("define")
    define.add_argument("name")
    define.add_argument("--type", default="text")
    define.add_argument("--label", default="")
    define.add_argument("--choice", action="append", default=[])
    define.set_defaults(handler=define_field)
    fset = fsub.add_parser("set")
    fset.add_argument("id")
    fset.add_argument("name")
    fset.add_argument("value")
    fset.set_defaults(handler=set_field)
    fsub.add_parser("list").set_defaults(handler=list_fields)

    merge = commands.add_parser("merge", help="merge a duplicate contact into another")
    merge.add_argument("keep")
    merge.add_argument("other")
    merge.set_defaults(handler=merge_contacts)

    search = commands.add_parser("search", help="find contacts")
    search.add_argument("words", nargs="+")
    search.add_argument("--all", action="store_true", help="include archived contacts")
    search.set_defaults(handler=search_contacts)

    dupes = commands.add_parser("dupes", help="contacts that look like the same person")
    dupes.add_argument("id", nargs="?")
    dupes.set_defaults(handler=show_dupes)


def _company_id(crm, name: str | None) -> str | None:
    if not name:
        return None
    return crm.companies.find_or_create(name).id


def add_contact(crm, args) -> bool:
    with crm.operation("add contact"):
        contact = crm.contacts.create(
            args.first_name,
            args.last_name,
            emails=args.email,
            phones=args.phone,
            company_id=_company_id(crm, args.company),
            title=args.title,
            owner=args.owner,
            source=args.source,
            tags=args.tag,
        )
    say(f"Added {contact.id} {contact.name}")
    return True


def show_contact(crm, args) -> bool:
    contact = crm.contact(args.id)
    if args.json:
        emit_json(crm.contacts.payload(contact))
        return False
    company = crm.contacts.company_of(contact)
    say(*contact_card(contact, company.name if company else ""))
    deals = crm.deals.for_contact(contact.id)
    if deals:
        say("  deals   " + ", ".join(f"{d.id} {d.title} ({d.stage})" for d in deals))
    open_tasks = crm.tasks(contact.id, open_only=True)
    if open_tasks:
        say("  tasks   " + ", ".join(f"{t.id} {t.title}" for t in open_tasks))
    return False


def list_contacts(crm, args) -> bool:
    contacts = crm.list_contacts(include_archived=args.all)
    if args.company:
        company = crm.companies.by_name(args.company)
        contacts = [c for c in contacts if company and c.company_id == company.id]
    if args.json:
        emit_json([crm.contacts.payload(c) for c in contacts])
    else:
        say(*(contact_line(c) for c in contacts))
    return False


def edit_contact(crm, args) -> bool:
    contact = crm.contact(args.id)
    changes = {}
    for option, key in (
        ("first", "first_name"),
        ("last", "last_name"),
        ("title", "title"),
        ("owner", "owner"),
        ("source", "source"),
    ):
        value = getattr(args, option)
        if value is not None:
            changes[key] = value
    if args.add_email:
        changes["emails"] = contact.emails + args.add_email
    if args.add_phone:
        changes["phones"] = contact.phones + args.add_phone
    with crm.operation("update contact"):
        if args.company is not None:
            changes["company_id"] = _company_id(crm, args.company)
        contact = crm.contacts.update(contact.id, **changes)
    say(f"Updated {contact.id} {contact.name}")
    return True


def archive_contact(crm, args) -> bool:
    contact = crm.archive_contact(args.id)
    say(f"Archived {contact.id} {contact.name}")
    return True


def unarchive_contact(crm, args) -> bool:
    contact = crm.unarchive_contact(args.id)
    say(f"Unarchived {contact.id} {contact.name}")
    return True


def add_company(crm, args) -> bool:
    company = crm.add_company(args.name, args.domain)
    say(f"Added {company.id} {company.name}")
    return True


def list_companies(crm, args) -> bool:
    for company in crm.list_companies():
        members = len(crm.companies.members(company.id))
        say(f"{company.id:<6} {company.name:<30} {members} contacts")
    return False


def rename_company(crm, args) -> bool:
    company = crm.rename_company(args.id, args.name)
    say(f"Renamed {company.id} to {company.name}")
    return True


def set_primary(crm, args) -> bool:
    company = crm.set_primary_contact(args.id, args.contact)
    say(f"{company.name}: primary contact {company.primary_contact_id or 'none'}")
    return True


def tag_contact(crm, args) -> bool:
    contact = crm.tag(args.id, *args.tags)
    say(f"{contact.id} {contact.name}: {', '.join(contact.tags) or 'no tags'}")
    return True


def untag_contact(crm, args) -> bool:
    contact = crm.untag(args.id, *args.tags)
    say(f"{contact.id} {contact.name}: {', '.join(contact.tags) or 'no tags'}")
    return True


def list_tags(crm, args) -> bool:
    for tag, count in crm.tag_counts().items():
        say(f"{tag:<24} {count}")
    return False


def list_tagged(crm, args) -> bool:
    say(*(contact_line(c) for c in crm.tagged(args.tag)))
    return False


def define_field(crm, args) -> bool:
    definition = crm.define_field(args.name, args.type, args.label, args.choice)
    say(f"Defined {definition.name} ({definition.type})")
    return True


def set_field(crm, args) -> bool:
    contact = crm.set_field(args.id, args.name, args.value)
    say(f"{contact.id} {args.name} = {contact.fields.get(args.name, '')}")
    return True


def list_fields(crm, args) -> bool:
    for definition in crm.field_definitions():
        choices = f"  [{', '.join(definition.choices)}]" if definition.choices else ""
        say(f"{definition.name:<20} {definition.type:<7} {definition.label}{choices}")
    return False


def merge_contacts(crm, args) -> bool:
    other = crm.contact(args.other)
    contact = crm.merge_contacts(args.keep, args.other)
    if args.json:
        emit_json(crm.contacts.payload(contact))
    else:
        say(f"Merged {other.id} {other.name} into {contact.id} {contact.name}")
    return True


def search_contacts(crm, args) -> bool:
    found = crm.search(" ".join(args.words), include_archived=args.all)
    if args.json:
        emit_json([crm.contacts.payload(c) for c in found])
    elif found:
        say(*(contact_line(c) for c in found))
    else:
        say("No matches.")
    return False


def show_dupes(crm, args) -> bool:
    if args.id:
        contact = crm.contact(args.id)
        others = crm.duplicates_of(contact.id)
        for other in others:
            reasons = ", ".join(crm.dedupe.reasons(contact.id, other))
            say(f"{other}  ({reasons})")
        if not others:
            say("No likely duplicates.")
        return False
    groups = crm.duplicates()
    for group in groups:
        say("  ".join(f"{cid} {crm.contact(cid).name}" for cid in group))
    if not groups:
        say("No likely duplicates.")
    return False
