# libsys

Circulation records for the town library: loans, renewals, returns, overdue
reports, overdue notices and holds. The branch desks run their own circulation
software; libsys imports what they export every night.

## Branches

Branches are listed in `branches.toml`, each with a code (`HAR`), a name
(`Harbour`), its UTC offset, how many days a loan lasts there, how many times a
loan can be renewed, and its fines. One branch is the default.

## The nightly import

```
libsys import samples/nightly-2026-03-02.csv
```

The file has one row per circulation event:

| column    | meaning                                                              |
|-----------|----------------------------------------------------------------------|
| `event`   | `issue`, `renew` or `return`                                         |
| `branch`  | the branch's code or name, in any case (`HIL`, `hil`, `Hillside`)    |
| `loan_no` | the loan's number                                                    |
| `member`  | member id, e.g. `M-1043`                                             |
| `barcode` | the copy's barcode                                                   |
| `title`   | the title, as the desk knows it                                      |
| `at`      | when it happened, ISO 8601 in UTC (`2026-02-07T10:15:00Z`)           |

Rules:

- Each branch's desk numbers its own loans, so a loan is identified by its
  branch together with its loan number: Harbour's loan 1043 and Hillside's
  loan 1043 are two different loans.
- An empty `branch` means the default branch: rows from the old desk system,
  from before Hillside joined, have no branch.
- A row naming a branch that isn't in `branches.toml` is rejected; the import
  lists rejected rows with their line numbers and doesn't stop.
- The desk corrects a loan by sending its `issue` event again with the same
  number; the later one replaces the earlier one. Importing the same file twice
  changes nothing.
- A loan is due `loan_days` after the day it was issued, counted in the
  branch's local time. Renewing it makes it due `loan_days` after the day of
  the renewal. A `renew` beyond the branch's `max_renewals`, or a `renew` or
  `return` for a loan we don't know, is rejected.
- The merge job that collects the desks' exports writes each desk's rows,
  oldest first, and then appends late corrections, so rows of different
  branches can be interleaved. Each branch's events are applied in the order
  they appear in the file.

Records are kept in `library.json` (or `--db PATH`).

## Overdue report and notices

```
libsys overdue --as-of 2026-03-02     # every open loan due before that day, by branch
libsys notices --as-of 2026-03-02     # one notice per member, listing all their overdue loans
libsys loans M-1043                   # a member's loans
```

A loan is overdue on the day after its due date. Fines are charged per day
overdue, up to the branch's cap.

## Holds

Members can place holds on a title at a branch; when a copy comes back, the
first member in line gets it (`libsys holds TITLE`).

## Development

```
python -m pytest
```
