# clinicbook

The appointment book for our group of clinics: clinicians, rooms, opening hours, one-off
and repeating appointments, reminders by SMS or email, a waitlist that books people into
freed-up slots, the front desk's daily agenda, calendar and spreadsheet exports, an import
of the old diary system's exports, backups, and a command line for all of it.

```
python -m clinicbook clinic add camden "Camden Clinic" --zone Europe/London
python -m clinicbook room add camden C1 "Room 1"
python -m clinicbook clinician add dr-osei "Dr Ama Osei" --clinic camden
python -m clinicbook patient add "Jo Bloggs" --phone "+44 7700 900001"
python -m clinicbook book --clinic camden --clinician dr-osei --room C1 --patient P0001 \
    --at "2026-03-02 09:00" --minutes 30
python -m clinicbook agenda camden 2026-03-02
python -m clinicbook jobs run
```

Everything lives in one JSON file (`--db`, default `clinicbook.json`, or `CLINICBOOK_DB`).
`--now` or `CLINICBOOK_NOW` (`2026-03-01T09:00`) fixes the clock, for scripts and tests.
From Python, `ClinicBook(store, clock=...)` is the entry point; `clock` is a function
returning the current time, and everything that needs "now" asks it.

## How it works

- **Clinics** have opening hours per weekday (one or more intervals such as
  `08:00-12:30, 13:30-18:00`; Monday to Friday 08:00-18:00 by default), closure days, and a
  `zone`, the IANA time zone name the website shows next to the address.
- **Clinicians** work at one or more clinics. **Rooms** belong to one clinic.
- **Appointments** start on the 5-minute grid (`grid_minutes`) and last a multiple of it.
  A booking must sit inside one opening interval of the clinic on a day it isn't closed,
  can't be in the past, and can't overlap another booked appointment of the same
  clinician, room or patient. Cancelled, completed and no-show appointments don't block
  anything.
- **Series** repeat an appointment daily, on weekdays, weekly, fortnightly or monthly, for a
  number of times or until a date. Occurrences that can't be booked (a clash, a closure)
  are skipped and listed in the result's `skipped`; the rest are booked.
- **Reminders** are planned when an appointment is booked: one per entry in the clinic's
  `reminder_hours` (or the `reminder_hours` setting, `[24, 2]` by default), each due that
  many hours before the start. Reminders that would already be due are not planned.
  Moving an appointment re-plans them; cancelling drops the unsent ones.
- **Jobs** (`clinicbook jobs run`, from cron every few minutes) send due reminders, mark
  booked appointments as no-shows once they ended more than `no_show_grace` minutes ago,
  retry failed webhooks, expire old waitlist entries and offer freed slots to the waitlist.
- **Slot search** tries a start every `slot_minutes` (15) from each opening time, on each
  day from the search start for `search_days` (28) days, and takes the first start where a
  clinician (in id order, unless one is asked for) and a room (in id order) are both free.
  `next_free_slot(clinic, minutes, after=..., before=...)` returns the first such slot at
  or after `after` (default now) that starts before `before`.
- **The waitlist** holds patients waiting for a slot at a clinic, optionally with one
  clinician and a window (`earliest`, `latest`). Offering goes through the entries
  longest-waiting first and books each into the first free slot in its window.
- **Messages** to patients (confirmations, reminders, cancellations, waitlist offers) are
  written to the outbox, the `messages` table; the gateways send them from there.
- **Webhooks**: with `webhook_url` set, every appointment event (`appointment.booked`,
  `.cancelled`, `.rescheduled`, `.completed`, `.no_show`, `waitlist.offered`) is POSTed as
  JSON: `{"event", "delivery", "at", "appointment": {"id", "clinic", "clinician", "room",
  "patient", "kind", "status", "start", "end", "minutes", "series"}}`, plus
  `previous_start` for a reschedule and `reason` for a cancellation. With
  `webhook_secret` set, the body's HMAC-SHA256 is in `X-Clinicbook-Signature`. Failed
  deliveries are retried by the jobs.
- **The audit log** records every appointment event and every change to a clinic.

### Reports and exports

- `agenda(clinic, day)`: the day's appointments in time order (`.rows`, `.render()`).
- `utilisation(clinic, first, last)`: booked minutes per room per day against the open
  minutes of the day.
- `no_shows(clinic)`: completed and no-show counts per clinician per month.
- `export_ical(...)`: an iCalendar file with one VEVENT per appointment (UID
  `<id>@clinicbook`, DTSTAMP, DTSTART, DTEND, SUMMARY, LOCATION, STATUS).
- `export_csv(...)`: columns `id, clinic, clinician, room, patient, patient_name, date,
  start, end, minutes, kind, status, series`.
- `import_csv(file)`: the old diary system's export, columns `clinic, clinician, room,
  patient_name, patient_phone, date, time, minutes, kind, status, notes`. Rows are taken
  as they are (no opening-hours or clash checks; they are history as much as plans).
  Patients are matched by phone number or created. A row already imported (same clinic,
  clinician and start) is skipped. Rows with errors are reported with their line number
  and left out.

## Data file

A JSON object: `version` (currently 1), `settings`, `counters`, and one list per table:
`clinics`, `rooms`, `clinicians`, `patients`, `appointments`, `series`, `reminders`,
`waitlist`, `messages`, `webhook_queue`, `audit`. These fields hold times:

| table           | time fields                       |
|-----------------|-----------------------------------|
| `appointments`  | `start`, `created`                |
| `series`        | `start`                           |
| `reminders`     | `due`, `sent`                     |
| `waitlist`      | `earliest`, `latest`, `added`     |
| `messages`      | `at`                              |
| `webhook_queue` | `next_attempt`                    |
| `audit`         | `at`                              |

Version 1 writes them as `YYYY-MM-DDTHH:MM`. Days (a clinic's `closures`) are
`YYYY-MM-DD` and opening hours `HH:MM-HH:MM`. Files written by clinicbook 0.x (no
`version`) still load and are saved in the current format.

## Backups

`clinicbook backup FILE` writes a zip holding `store.json`, the data file, and
`manifest.json`: `{"format": 1, "store_version": <the data file's version>, "taken_at":
<time>, "counts": {<table>: <rows>}}`. `clinicbook restore FILE` checks the counts and
replaces the data file with the backup's.

## Time zones

clinicbook was written for the Camden clinic, and every time in it is a plain local time
without a zone. Now that we have clinics in New York and Sydney too, that's wrong in more
places than it's right: a clinician who works in two clinics can be double-booked,
reminders go out hours early or late, and the exports put appointments at the wrong time
in anyone's calendar. This is how it has to work:

1. A clinic's `zone` is its time zone. Adding a clinic whose zone isn't in the system's
   time zone database fails with `ValidationError`.
2. Times given to clinicbook for a clinic are that clinic's wall-clock time when they are
   naive: the start of a booking, a series or a reschedule, the `after` and `before` of a
   slot search, a waitlist entry's `earliest` and `latest`, the CLI's `--at`, `--after`,
   `--earliest` and `--latest`, and the date and time of an imported row. Aware datetimes
   are accepted too and mean that instant.
3. A naive local time that doesn't exist (the hour skipped when the clocks go forward) is
   rejected with `InvalidTime`; an imported row with one is reported as an error. A local
   time that happens twice (when the clocks go back) means the first of the two
   (`fold=0`).
4. Every time clinicbook hands back for a clinic is an aware `datetime` in that clinic's
   zone: `Appointment.start` and `.end`, `Reminder.due`, the `start` and `end` of slots
   and agenda rows, a waitlist entry's `earliest` and `latest`. The agenda, the CSV
   export, messages and the CLI show the clinic's local time.
5. Durations are real time: a 60-minute appointment ends 60 minutes after it starts,
   whatever the clocks do in between. Appointments clash when their real time spans
   overlap, whichever clinics they are in: a clinician can't be seen in New York at 10:00
   and in London at 15:00 on the same January day, but can be at 10:00 in both.
6. An appointment must fit one opening interval of its clinic, judged by its local start
   and local end on the local day it starts.
7. A series repeats at the same local wall-clock time: a weekly 09:00 stays at 09:00 when
   the clocks change. An occurrence whose local time doesn't exist that day is skipped
   and listed in `skipped` like one that clashes.
8. "Now" (what `clock` returns, `--now`, `CLINICBOOK_NOW`) is an instant: an aware
   datetime, or a naive one meaning UTC. `--now` and `CLINICBOOK_NOW` are written
   `2026-03-07T13:00:00Z`, and the older form without seconds and `Z` means UTC as well.
9. A reminder `N` hours before an appointment is due exactly `N` hours of real time before
   it starts. Reminders, no-shows, waitlist windows, "not in the past" and webhook retries
   all compare instants.
10. A slot search walks the clinic's local days and local opening hours, starting from
    `after` (default now) taken in the clinic's zone, and skips local times that don't
    exist.
11. An agenda or a utilisation report covers the clinic's local day, from local midnight
    to the next local midnight.
12. The iCalendar export writes DTSTART, DTEND and DTSTAMP in UTC:
    `DTSTART:20260302T140000Z`.
13. The CSV export keeps `date`, `start` and `end` in the clinic's local time and adds two
    columns at the end, `utc_start` and `utc_end` (`2026-03-02T14:00:00Z`).
14. Webhook payloads write every time in UTC (`2026-03-02T14:00:00Z`): `at`, the
    appointment's `start` and `end`, and `previous_start`. The appointment also carries
    its clinic's `zone`.
15. The data file becomes version 2: every time field in the table above holds a UTC
    instant written `YYYY-MM-DDTHH:MM:SSZ`. Closure days and opening hours stay local.
    clinicbook always saves version 2, and a backup's `taken_at` is written the same way.
16. Data files and backups written before (version 1 or 0.x) keep loading and restoring.
    Their times are the local time of the clinic the record belongs to (an appointment's or
    a series' clinic, the clinic of a reminder's appointment, a waitlist entry's clinic),
    read by rule 3, except that a time that doesn't exist is moved forward by the length of
    the gap. The times of records that belong to no clinic (messages, the webhook queue,
    the audit log) are UTC.

## Layout

The package is `clinicbook/`; `ClinicBook` in `clinic.py` wires the services together and
is the public API, `cli.py` is the command line. `tests/` has the test suite
(`python -m pytest`); `tests/data/` holds data files written by earlier releases, which
must keep loading.
