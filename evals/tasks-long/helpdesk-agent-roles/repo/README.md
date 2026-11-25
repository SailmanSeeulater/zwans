# deskline

A small helpdesk for small support teams. Customers write in by email (or an agent opens a
ticket for them); tickets land in queues, agents answer them, macros take care of the
repetitive parts, and the SLA job makes sure nothing sits around for too long. Everything
lives in one JSON file, and there is a Python API, a JSON API layer for the web front end,
and a command line.

Python 3.12, standard library only.

```bash
python -m deskline --db desk.json init
python -m deskline --db desk.json agent add maria "Maria Lopez" maria@ourdesk.example
python -m deskline --db desk.json customer add "Jane Doe" --email jane@example.org --phone "+1 555 0101"
python -m deskline --db desk.json ticket new C-1 "Printer on fire" "It is on fire. Again."
python -m deskline --db desk.json --as maria ticket take T-1
python -m deskline --db desk.json --as maria ticket reply T-1 "Have you tried water?"
```

## Concepts

- **Customers** (`C-1`, `C-2`, ...) have a name and, optionally, an email address, a phone
  number, a postal address, an organization and tags. The email address is unique; the mail
  gateway uses it to recognise senders.
- **Agents** answer tickets. An agent has a handle as its id (`maria`), a name, an email
  address for notifications, an optional signature, and can be deactivated (their open
  tickets go back to the queue).
- **Teams** group agents. **Queues** (`general`, `billing`, ...) sort tickets: a queue can
  belong to a team, whose members are told about new tickets in it, can have a default
  priority, and can have keywords: a new ticket whose subject or first message contains one
  of a queue's keywords goes to that queue (the first matching queue by id), otherwise to the
  default queue (`general`).
- **Tickets** (`T-1`, ...) have a subject, a requester (a customer), a status, a priority
  (`low`, `normal`, `high`, `urgent`), a queue, an optional assignee, tags, and a
  conversation of comments. Comments are public (replies, the customer's messages) or
  internal notes. A comment that came in by email remembers the address it came from.
- **Statuses**: `new` → `open`, `pending` or `solved`; `open` ↔ `pending`; either → `solved`;
  `solved` → `open` or `closed`; `closed` is final. An agent's first reply opens a new ticket;
  a customer's reply reopens a pending or solved ticket; assigning a new ticket opens it.
- **Macros** (`M-1`, ...) are canned lists of actions applied to a ticket in one go:
  `set_status`, `set_priority`, `set_queue`, `add_tag`, `remove_tag`, `assign` (to a given
  agent), `assign_self`, `reply` and `note`. Reply and note texts are templates (see below)
  rendered against the ticket. Applying a macro is all or nothing.
- **Bulk updates** change many tickets at once (status, priority, queue, assignee, tags);
  also all or nothing.
- **Merging** copies a duplicate ticket's conversation and tags onto another ticket and
  closes the duplicate (`merged_into` points at the ticket it went into).
- **Saved searches** (`Q-1`, ...) are named queries. They belong to the agent who saved them
  and can be shared with everyone.
- **SLAs**: each priority has a first-reply target and a resolution target, in minutes from
  the ticket's creation. Defaults: urgent 30/240, high 60/480, normal 240/1440, low
  480/2880. The breach job marks tickets that missed a target and emails their assignee (or,
  for unassigned tickets, the queue's team).
- **Surveys**: when a ticket is solved for the first time, the requester gets a survey email
  with a token; they answer with a rating from 1 to 5.
- **The audit log** records every change: when, who (an agent id, or `system`), what
  (`ticket.created`, `customer.updated`, ...), on which record, and details.

## Mail

The mail gateway (`deskline.mail.inbound.receive(ctx, raw_message)`, or
`deskline mail-in FILE`) turns inbound mail into tickets. Mail whose subject carries a
`[T-12]` tag of a ticket of the same customer becomes a reply on it (a closed ticket gets a
new follow-up ticket instead); anything else becomes a new ticket, and unknown senders
become customers. Quoted history and signatures are cut off; automatic replies are dropped.

Outgoing mail goes to the outbox (`store.outbox`, `deskline outbox`), from which a separate
sender delivers it. Mail is rendered from built-in templates:

| Template | Goes to | When |
|---|---|---|
| `customer_ack` | the requester | a ticket is created |
| `customer_reply` | the requester | an agent replies |
| `survey_request` | the requester | a ticket is solved the first time |
| `agent_new_ticket` | the queue's team | a ticket arrives in a queue with a team |
| `agent_assigned` | the new assignee | a ticket is assigned |
| `agent_customer_replied` | the assignee (or the team) | the customer replies |
| `agent_sla_breach` | the assignee (or the team) | an SLA target is missed |

Agents never get mail about their own actions. Templates use `{{ customer.name }}`
placeholders, filters (`{{ ticket.created_at | date }}`), `{% if %}` and `{% for %}` blocks.
`deskline.mail.preview.preview(ctx, name, ticket_id)` renders a template against a ticket
without sending it.

## Python API

```python
from deskline import Desk
from deskline.services import customers, tickets

desk = Desk.open("desk.json")          # or Desk.create(path), Desk.memory()
ctx = desk.context()                   # acting as the system
maria = desk.context("maria")          # acting as agent maria

jane = customers.create(ctx, "Jane Doe", email="jane@example.org")
ticket = tickets.create(ctx, jane.id, "Printer on fire", "It is on fire.")
tickets.take(maria, ticket.id)
tickets.reply(maria, ticket.id, "Have you tried water?")
```

`Desk(store, clock)` takes a clock (a callable returning an ISO timestamp) so scripts and
tests can control time; `deskline.clock.SteppingClock` is a handy one. Every change runs in
a transaction and is saved to the file when it commits; a change that fails leaves nothing
behind.

Every service function takes a context first. The context says who is acting: an agent, or
the system (scripts, the mail gateway, scheduled jobs, the CLI without `--as`).

| Module | Functions |
|---|---|
| `deskline.services.customers` | `create`, `update`, `get`, `list_customers`, `tickets_of`, `delete` |
| `deskline.services.agents` | `create_agent`, `update_agent`, `set_active`, `list_agents`, `create_team`, `add_member`, `remove_member`, `list_teams` |
| `deskline.services.queues` | `create_queue`, `update_queue`, `list_queues` |
| `deskline.services.tickets` | `create`, `get`, `list_tickets`, `reply`, `note`, `set_status`, `set_priority`, `set_queue`, `add_tag`, `remove_tag`, `assign`, `take`, `delete` |
| `deskline.services.macros` | `create_macro`, `update_macro`, `delete_macro`, `list_macros`, `apply_macro` |
| `deskline.services.bulk` | `bulk_update(ctx, ticket_ids, changes)` |
| `deskline.services.merging` | `merge(ctx, source_id, target_id)` |
| `deskline.services.searches` | `save_search`, `list_searches`, `get_search`, `delete_search`, `run_saved` |
| `deskline.services.sla` | `set_policy`, `policies`, `check_breaches` |
| `deskline.services.surveys` | `respond(ctx, token, rating, remark="")` |
| `deskline.services.settings` | `set_setting`, `all_settings` |
| `deskline.search` | `run(ctx, query, sort="updated", limit=None)` → result rows |
| `deskline.export.csv_export` | `export_tickets(ctx, out, text="")`, `export_customers(ctx, out)`, `tickets_csv`, `customers_csv` |
| `deskline.export.importer` | `import_customers(ctx, csv_text)` |
| `deskline.export.backup` | `dump(ctx)`, `dumps(ctx)`, `restore(ctx, document)` |
| `deskline.reports.sla_report`, `.workload`, `.satisfaction` | `build(ctx, ...)` → dict, `render(report)` → text |
| `deskline.auditview` | `entries(ctx, target=, actor=, action=, since=, limit=)`, `render(rows)`, `history(ctx, ticket_id)` |
| `deskline.mail.preview` | `preview(ctx, name, ticket_id)`, `list_templates()` |
| `deskline.jobs` | `run_all(ctx)`: the SLA breach check, auto-closing solved tickets, purging old sent mail |

Search result rows (from `search.run` and `searches.run_saved(...)["results"]`) have `id`,
`subject`, `status`, `priority`, `queue`, `assignee`, `tags`, `requester` (the customer's
name), `requester_email`, `created_at` and `updated_at`.

## Search

Terms are ANDed; `-` negates a term:

```
status:open,pending  priority:high  queue:billing  tag:vip  -tag:spam
assignee:maria  assignee:me  assignee:none  customer:C-4  requester:jane
email:example.org  phone:555  created>2026-03-01  updated<2026-04-01
is:breached  is:unassigned  is:active  is:merged  "exact phrase"  printer
```

Bare words match the subject and the public conversation. `requester:` matches the
customer's name, `email:` part of their email address, `phone:` the digits of their phone
number. `me` is whoever runs the search, also when it is a saved search.

## JSON API

`deskline.api.dispatch(desk, request)` takes a request dict and returns a response dict
(`handle_json` does the same with JSON text). This is what the web front end talks to.

```json
{"action": "tickets.reply", "agent": "maria", "params": {"id": "T-1", "body": "Hello"}}
{"ok": true, "data": {...}}
{"ok": false, "error": {"code": "not_found", "message": "no ticket 'T-9'"}}
```

`agent` is the agent making the request; without it the request acts as the system. Error
codes: `invalid`, `not_found`, `conflict`, `unknown_action`.

| Action | Params | Returns |
|---|---|---|
| `tickets.create` | `customer`, `subject`, `body`, `priority`?, `queue`?, `tags`? | ticket |
| `tickets.get` | `id` | ticket |
| `tickets.list` | `status`?, `queue`?, `assignee`?, `customer`? | rows |
| `tickets.reply`, `tickets.note` | `id`, `body` | ticket |
| `tickets.update` | `id`, `status`?, `priority`?, `queue`?, `add_tags`?, `remove_tags`? | ticket |
| `tickets.assign` | `id`, `agent` (missing or empty: unassign) | ticket |
| `tickets.take` | `id` | ticket |
| `tickets.merge` | `source`, `target` | the target ticket |
| `tickets.delete` | `id` | `{"deleted": true}` |
| `tickets.bulk` | `ids`, `changes` | rows |
| `tickets.search` | `query`, `sort`?, `limit`? | rows |
| `customers.create` | `name`, `email`?, `phone`?, `address`?, `organization`?, `tags`? | customer |
| `customers.get` | `id` | customer, with `tickets` |
| `customers.list` | `text`? | customers |
| `customers.update` | `id` and any of `name`, `email`, `phone`, `address`, `organization`, `tags` | customer |
| `customers.delete` | `id` | `{"deleted": true}` |
| `agents.create` | `id`, `name`, `email`, `signature`? | agent |
| `agents.list` | `include_inactive`? | agents |
| `agents.update` | `id`, `name`?, `email`?, `signature`? | agent |
| `macros.create` | `name`, `actions` | macro |
| `macros.list` | | macros |
| `macros.apply` | `macro`, `ticket` | ticket |
| `macros.delete` | `id` | `{"deleted": true}` |
| `searches.save` | `name`, `query`, `shared`?, `sort`? | saved search |
| `searches.list` | | saved searches |
| `searches.run` | `id`, `limit`? | `{"search", "count", "results"}` |
| `reports.sla`, `reports.satisfaction` | `since`? (`reports.sla` also `queue`?) | report |
| `reports.workload` | | report |
| `audit.list` | `target`?, `actor`?, `action`?, `since`?, `limit`? | audit entries |
| `templates.preview` | `template`, `ticket` | `{"template", "audience", "subject", "body"}` |
| `export.tickets` | `query`? | `{"csv": text}` |
| `export.customers` | | `{"csv": text}` |

A ticket is returned with its `requester` (`id`, `name`, `email`, `phone`, `organization`)
and its `comments` (each with `from_address`); a customer with `email`, `phone` and
`address`.

## Command line

```
deskline [--db FILE] [--as AGENT] COMMAND ...
```

`--db` defaults to `$DESKLINE_DB` or `desk.json`. `--as` says which agent is acting; without
it the CLI acts as the system. Exit status 0 on success, 1 when deskline refuses or fails
(with `error: ...` on stderr), 2 for usage errors.

```
init
customer add NAME [--email --phone --address --org --tag]   customer list [TEXT]
customer show ID   customer edit ID [--name --email --phone --address --org]
customer delete ID   customer import FILE.csv
agent add ID NAME EMAIL [--signature]   agent list [--all]   agent activate|deactivate ID
team add ID NAME   team join|leave TEAM AGENT
queue add ID NAME [--team --priority --keyword ...]   queue list
ticket new CUSTOMER SUBJECT BODY [--priority --queue --tag]   ticket show ID [--public]
ticket list [--status --queue --assignee]   ticket reply|note ID TEXT
ticket status|priority|tag|untag|assign|move ID VALUE   ticket take|delete|history ID
ticket merge SOURCE TARGET
macro add NAME --action TYPE[=VALUE] ...   macro list   macro run MACRO TICKET   macro delete ID
search QUERY [--sort --limit]
saved add NAME QUERY [--shared --sort]   saved list   saved run ID   saved delete ID
bulk ID... [--status --priority --queue --assignee --add-tag --remove-tag]
export tickets [--query Q] [--out FILE]   export customers [--out FILE]
report sla|workload|satisfaction [--json] [--since]
audit [--target --actor --action --since --limit]
mail-in FILE   outbox [--all]   jobs run
sla show   sla set PRIORITY FIRST_REPLY_MINUTES RESOLUTION_MINUTES
template list   template preview NAME TICKET
setting show   setting set KEY VALUE
backup FILE   restore FILE   survey TOKEN RATING [REMARK]
```

## Storage

The helpdesk is one JSON file, `{"format": "deskline", "version": 3, "data": {...}}`,
rewritten atomically after every change. Files from older versions are upgraded when they
are read: version 1 kept a customer's email and phone in one `contact` string and called the
assignee `assigned_to`; version 2 kept ticket tags as a comma-separated string. A file
newer than this deskline is refused.

`deskline backup FILE` writes the whole helpdesk as one document (the same shape as the
file); `deskline restore FILE` replaces everything with a backup.

## Settings

`desk_name`, `support_address`, `auto_close_days` (solved tickets close after this many days;
default 4), `survey_on_solve` (default true), `outbox_keep_days` (sent mail is purged after
this many days; default 30), `default_queue` (default `general`).

## Roles and permissions

Every agent has a **role**: `viewer`, `agent`, `lead` or `admin`. The role decides what the
agent may do and whether they may see customers' contact details.

- `agents.create_agent(ctx, agent_id, name, email, signature="", role="agent")` and
  `agents.set_role(ctx, agent_id, role)` set it; an unknown role is a `ValidationError`.
  An agent created without a role is an `agent`, and agents in files written before roles
  existed are `agent`s. The role is stored as a `role` field on the agent; the file format
  needs no other change.
- The JSON API shows an agent's `role` in agent records; `agents.create` takes an optional
  `role`, and `agents.set_role` (`id`, `role`) changes it.
- The CLI: `agent add ID NAME EMAIL --role ROLE`, `agent role ID ROLE`, and `agent list`
  shows each agent's role.
- The system (a context without an agent: scripts, the mail gateway, jobs, the CLI without
  `--as`, API requests without `agent`) may do everything and sees everything, as before.

### Permissions

| Permission | Allows | viewer | agent | lead | admin |
|---|---|:-:|:-:|:-:|:-:|
| `ticket.view` | reading tickets and ticket lists, searching, running saved searches, listing macros and saved searches, the reports, template previews, the outbox listing | ✓ | ✓ | ✓ | ✓ |
| `customer.view` | reading customers and customer lists | ✓ | ✓ | ✓ | ✓ |
| `ticket.create` | creating tickets | | ✓ | ✓ | ✓ |
| `ticket.note` | internal notes, on any ticket | | ✓ | ✓ | ✓ |
| `ticket.edit` | public replies, status, priority, queue and tag changes, taking a ticket | | own | ✓ | ✓ |
| `ticket.assign` | assigning a ticket to another agent, unassigning it | | | ✓ | ✓ |
| `ticket.delete` | deleting tickets | | | | ✓ |
| `customer.edit` | creating and changing customers, importing customers | | ✓ | ✓ | ✓ |
| `customer.delete` | deleting customers | | | | ✓ |
| `contact.view` | seeing contact details (see Redaction) | | | ✓ | ✓ |
| `macro.run` | applying macros | | ✓ | ✓ | ✓ |
| `macro.manage` | creating, changing and deleting macros | | | ✓ | ✓ |
| `search.save` | saving (unshared) searches and deleting your own | | ✓ | ✓ | ✓ |
| `search.share` | saving a shared search | | | ✓ | ✓ |
| `export` | the CSV exports | | ✓ | ✓ | ✓ |
| `audit.view` | the audit log viewer and ticket history | | ✓ | ✓ | ✓ |
| `sla.manage` | changing SLA policies | | | | ✓ |
| `admin` | agents, roles, teams, queues, settings, backups and restores, running the jobs | | | | ✓ |

**own**: an `agent` has `ticket.edit` on tickets that are unassigned or assigned to them, and
not on tickets assigned to someone else.

How operations map onto permissions, where it isn't obvious:

- Taking a ticket, or assigning it to yourself, needs `ticket.edit` on it; so an agent can
  take an unassigned ticket but not one assigned to someone else. Assigning to anyone else,
  or unassigning, needs `ticket.assign`.
- **Macros** need `macro.run`, and every action needs the permission it would need on its
  own (`set_*`, tags, `reply` and `assign_self`: `ticket.edit`; `note`: `ticket.note`;
  `assign`: `ticket.assign`, or `ticket.edit` when it assigns the agent applying it). Each
  action is checked when it runs, against the ticket as it is at that point.
- **Bulk updates** check every change on every ticket, as if they were made one by one.
- **Merging** needs `ticket.edit` on both tickets.
- **Saved searches** run with the permissions of whoever runs them, not of their owner.
- Search terms on contact details (`email:` and `phone:`) need `contact.view`, in every
  search: `search.run`, saved searches, the ticket export's query.
- The mail gateway and `surveys.respond` act for customers and need no permission.

A **denied** operation raises `deskline.errors.PermissionDenied`, a `DesklineError` whose
`code` is `forbidden` and whose `permission` attribute names the missing permission (for a
macro, bulk update or merge, the first one found missing). It changes nothing: like every
operation it is all or nothing, so a macro, bulk update or merge refused halfway leaves no
partial changes. The refusal itself is recorded in the audit log: actor the agent, action
`permission.denied`, target the ticket (or other record) refused, if there is one, and
`permission` in the details. That entry stays (and is saved to the file) even though the
operation failed.

The JSON API answers a denied request with error code `forbidden`. The CLI prints
`denied: <reason>` to stderr and exits with status 3.

### Redaction

A customer's **contact details** are their email address, phone number and postal address.
Without `contact.view`, every output shows each of these fields as `[redacted]` (an empty
field stays empty). That covers everything people or programs read from deskline:

- JSON API responses: customers, a ticket's `requester`, the `from_address` of comments,
  rows, reports, audit entries, previews and exports;
- search results from `search.run` and `searches.run_saved` (`requester_email`);
- the CSV exports (`requester_email` and `requester_phone` for tickets; `email`, `phone`
  and `address` for customers);
- the reports (`email` and `phone` in the SLA report's missed targets and in the
  satisfaction report's follow-up list), both `build` and `render`;
- the audit log viewer (`auditview.entries`, `render` and `history`): the `email`, `phone`,
  `address` and `from_address` values in an entry's details, including inside `changes`;
- email rendered for agents: notifications are rendered for the role of the agent
  receiving them, previews for the role of the agent asking. Mail to customers is never
  redacted;
- everything the CLI prints.

Redaction is about fields, not free text: what a customer writes in a message is shown as
is. The Python service functions that return records (`tickets.get`, `customers.get`, ...)
return them whole; they are the trusted core the outputs are built on. The stored file and
backups are never redacted.
