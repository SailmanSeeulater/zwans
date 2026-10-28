# orderdesk

A small event-sourced order desk: placing orders, taking payment, shipping, cancelling.
Run it with `python -m orderdesk --help`.

```
python -m orderdesk place --customer alice --email alice@example.com --line MUG-01:2:9.50
python -m orderdesk pay ORD-0001 --amount 19.00
python -m orderdesk ship ORD-0001 --carrier PostNL --tracking 3S1234
python -m orderdesk --role manager report
```

Everything is kept in a data folder (`--data`, default `orderdesk-data/`):

| file           | what                                                    |
|----------------|---------------------------------------------------------|
| `events.jsonl` | the event log, the only source of truth                 |
| `audit.jsonl`  | every command anyone tried, and what came of it         |
| `outbox.jsonl` | customer emails waiting for the mailer to send them     |

`ORDERDESK_NOW` (e.g. `2026-03-01T09:00:00Z`) fixes the clock, for scripts and tests.

## How it fits together

```
CLI ──> command ──> Desk.execute ──> handler(state, command) ──> events ──> store
                       │                                          │
                 permission, validation,                          └──> bus ──> read models
                 audit entry                                                   notifications
```

- `orderdesk/events.py`: the events, registered with `@event` under the name they are
  stored as.
- `orderdesk/aggregate.py`: `OrderState`, rebuilt by replaying an order's events.
- `orderdesk/commands.py`: the command registry (`@handler`).
- `orderdesk/handlers/`: one module per command: the command dataclass and its handler.
- `orderdesk/dispatcher.py`: `Desk`, which runs commands.
- `orderdesk/permissions.py`: roles and their permissions.
- `orderdesk/projections.py`: read models for the views and reports.
- `orderdesk/notifications.py`, `orderdesk/templates.py`: customer emails.
- `orderdesk/cli.py`: the command line.

## Adding a command

1. Write the command dataclass and its handler in a new module under `orderdesk/handlers/`,
   registered with `@handler` (name, permission, summary).
2. Import the module in `orderdesk/handlers/__init__.py`.
3. If it needs a new permission, give it to the right roles in `orderdesk/permissions.py`.
4. Add a sub-parser and a builder in `orderdesk/cli.py`.
5. Document it in `docs/commands.md`.

A new event also needs `@event` registration and an applier in `aggregate.py`.

## Tests

`python -m pytest`
