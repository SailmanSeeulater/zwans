# orbit

A small CRM for a small team: contacts and the companies they work for, deals moving
through a pipeline, notes, tasks and emails logged against contacts, tags, custom fields,
an activity timeline, duplicate detection, full-text search, webhooks, CSV import and
export, undo, backups and a few reports. Everything lives in one JSON file.

```
python -m orbit contact add Ada Lovelace --email ada@analytical.example --company "Analytical Engines" --tag vip
python -m orbit note c1 "Wants a quote for the difference engine"
python -m orbit deal add "Difference engine" --amount 12,000 --contact c1
python -m orbit deal move d1 qualified --contact c1
python -m orbit timeline c1
python -m orbit search lovelace
python -m orbit dupes
python -m orbit undo
python -m orbit report pipeline
```

`--db PATH` picks the data file (default `$ORBIT_DB`, else `./orbit.json`); `--json` makes
the commands that show things print JSON. `ORBIT_NOW` (e.g. `2026-03-01T09:00:00Z`) fixes
the clock: time starts there and moves on by one second per reading, for scripts and tests.

## From Python

```python
from orbit import Crm

crm = Crm.open("orbit.json")          # or Crm.memory()
ada = crm.add_contact("Ada", "Lovelace", emails=["ada@analytical.example"], tags=["vip"])
crm.add_note(ada.id, "Wants a quote")
deal = crm.add_deal("Difference engine", 1_200_000, [ada.id])
crm.move_deal(deal.id, "qualified", contact_id=ada.id)
crm.search("quote")                    # [Contact(id="c1", ...)]
crm.undo()                             # "move deal"
crm.save()
```

Every change goes through a `Crm` method (or a CLI command, which calls them) and is one
undo step. Ids are a prefix and a number: contacts `c1`, companies `co1`, deals `d1`,
notes `n1`, tasks `t1`, logged emails `e1`, webhook subscriptions `wh1`.

## What's in it

**Contacts** have a first and last name, any number of email addresses and phone numbers
(the first email is the primary one), a company, a title, an owner, a source, tags, custom
field values, a status (`active` or `archived`) and `last_contacted_at`, the time of the
most recent email logged with them. Contacts are archived rather than deleted.

**Companies** have a name (unique, ignoring case), a domain and optionally a primary
contact.

**Deals** have a title, an amount in cents, a stage (`lead`, `qualified`, `proposal`,
`negotiation`, `won`, `lost`), one or more contacts (the first is the main one), an owner,
and a stage history: one entry per stage the deal entered, with the time and, optionally,
the contact whose conversation led to the move.

**Notes, tasks and emails** are logged against one contact each. Tasks have an optional
due date and can be completed; `orbit reminders` lists the open ones that are due.

**The timeline** of a contact lists everything that happened with them, oldest first:
created, changed, notes, emails, tasks, deals and stage moves. Each entry shows the
contact's name; when a contact is renamed, its timeline shows the new name.

**Tags** are lower case words (`vip`, `trade-show-2026`); `crm.tagged("vip")` lists the
contacts that have one and `crm.tag_counts()` counts them.

**Custom fields** are defined once (`crm.define_field("size", "choice", choices=[...])`)
and then set per contact. Types: `text`, `number`, `date` (YYYY-MM-DD), `choice` (one of the
choices) and `multi` (a list of choices). Setting a field to None, "" or [] clears it.

**Duplicates**: two active contacts look like the same person when they share an email
address (ignoring case), a phone number (its last nine digits) or a full name (ignoring
case and accents). `crm.duplicates()` lists the groups of contact ids that look like one
person; `crm.duplicates_of(id)` lists the ones that look like a given contact.

**Search** (`crm.search(text)`, `orbit search`) finds contacts by their name, email
addresses, phone numbers, company, title, tags, custom field values, the text of their
notes and the subjects of their logged emails. Every word must match; the last one may be
the start of a word. Archived contacts are left out unless asked for.

**Webhooks**: `crm.subscribe(url, events, contact_id=None)` subscribes a URL to some events
(or `"*"` for all), optionally only those about one contact. The events are
`contact.created`, `contact.updated`, `company.created`, `company.updated`, `deal.created`,
`deal.updated`, `deal.stage_changed`, `note.added`, `task.added`, `task.completed` and
`email.logged`. Each change puts one message per interested subscription in the outbox, in
the same step as the change; `orbit deliver` sends them (signed, retried with backoff).
Payloads use the shapes in `orbit/payloads.py`: a contact event's payload is
`{"contact": {...}}` (plus `"changed": [...]` for `contact.updated`), a deal event's is the
deal, and so on. An event is "about" a contact when it's the contact's own event, a deal
the contact is on, or a note, task or email logged against them.

**Import and export**: `orbit import FILE` reads contacts from CSV (columns `id`,
`first_name`, `last_name`, `email`, `phone`, `company`, `title`, `owner`, `source`, `tags`
and `field:<name>`; several values in a cell are separated by `;`). A row updates the
contact its `id` names, or else the contact that already has one of its email addresses,
or else creates a new contact. `orbit export csv` writes the same columns.
`orbit export contact ID` writes everything about one contact as JSON (its details, notes,
tasks, emails, deals and timeline); `orbit export vcard` writes vCards.

**Reports** (`orbit report ...`, or `orbit.reports` from Python): `contacts` (counts by
owner, source, company and tag), `pipeline` (deals and amounts per stage, win rate),
`activity` (notes, emails, open tasks, deals and open deal value per contact), `top`
(contacts by open deal value) and `stages` (average days in each stage).

**Undo**: `crm.undo()` / `orbit undo` undoes the last change, whatever it was; it can be
repeated, up to 50 changes back, and works across runs because the undo history is saved
in the data file. `orbit history` shows what it would undo. Undo puts the data back as it
was; it sends no webhooks, and messages already in the outbox stay there.

**Backups**: `orbit backup` saves a copy of the data file in `backups/` next to it;
`orbit restore FILE` brings one back (the restored file starts with no undo history).

## The data file

One JSON document:

```json
{"format": "orbit", "version": 2,
 "tables": {"contacts": {"c1": {...}}, "companies": {...}, "deals": {...}, ...},
 "undo": [...]}
```

Files written by orbit 0.x (version 1, where a contact had a single email and phone and a
deal a single contact) still open; they are upgraded in memory and saved in the current
format. `tests/data/v1.json` is one.

## Layout

| path              | what                                                            |
|-------------------|-----------------------------------------------------------------|
| `orbit/crm.py`    | `Crm`, which wires everything together                          |
| `orbit/models/`   | the records                                                     |
| `orbit/services/` | the logic for each kind of record, the timeline, webhooks, undo |
| `orbit/index/`    | the in-memory search, duplicate and tag indexes                 |
| `orbit/store/`    | the data file, upgrades of old files, backups                   |
| `orbit/io/`       | CSV import and export, JSON and vCard export                    |
| `orbit/reports/`  | reports                                                         |
| `orbit/jobs/`     | webhook delivery, reminders, index checks                       |
| `orbit/cli/`      | the command line                                                |

## Tests

`python -m pytest`

## Merging contacts

Sales keep adding the same person twice. Merging fixes that:
`crm.merge_contacts(keep_id, other_id)` (CLI: `orbit merge KEEP OTHER`) merges the contact
`other_id` (call it B) into `keep_id` (call it A) and returns A as it is after the merge.
Merging a contact into itself is an error (`CrmError`); so is an id that names no contact
(`NotFound`).

**A after the merge** keeps its own id, name, title, owner, source, status and creation
time, and gets:

- its own email addresses followed by B's that it didn't have (compared ignoring case);
  the same for phone numbers (compared by their digits);
- the tags of both;
- for each custom field, A's value if A has one, otherwise B's (a value that is missing,
  None, "" or [] counts as none); `multi` fields instead get A's values followed by B's
  values that A didn't have;
- A's company, or B's if A has none;
- `last_contacted_at`: the later of the two.

**Everything that pointed at B points at A**:

- B's notes, tasks and logged emails;
- deals: A takes B's place in the deal's contacts (a deal that had both lists A once, in
  A's place) and in the deal's stage history;
- companies whose primary contact was B;
- B's timeline entries, which from then on show A's name; the merge also adds one entry to
  A's timeline, of kind `merged`, whose `ref` is B's id;
- webhook subscriptions that followed B follow A.

**B is gone**: it no longer appears in contact lists, search results, duplicates, tag
lookups, reports or exports. Its id still works, though: wherever orbit accepts a contact
id (every `Crm` method, every CLI command, the `id` column of an import, the JSON contact
export), B's id means A. That holds for merges in a row (B merged into A, then A into C:
B means C), and it survives saving, reopening, backups and restores. B's id is never given
to a new contact.

**Search, duplicates and tags** know about the merge straight away: A is found by
everything B brought along (B's addresses, phone numbers, tags, notes and emails), but not
by B's name, which A doesn't take; A's new addresses and numbers count for duplicates and
for matching import rows by email.

**Webhooks**: a merge sends exactly these events, in this order: one `deal.updated` for
each deal it changed, in deal id order, then one `contact.merged` with the payload
`{"contact": {...A, in the usual contact shape...}, "merged_id": "<B's id>"}`. It sends
nothing else (no `contact.updated`). `contact.merged` is about A, and subscriptions can ask
for it like any other event.

**Undo**: a merge is one undo step. `undo` right after it puts everything back as it was
before, B and its id included, and search, duplicates and tags see B again.

Merging needs no new data file version; files stay version 2.
