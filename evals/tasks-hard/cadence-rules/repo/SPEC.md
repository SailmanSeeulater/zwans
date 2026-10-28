# Cadence rules

A *cadence rule* is a short line of text that says on which dates something recurring
happens: payroll runs, invoice dates, report deadlines. This document is the complete
definition. Where it says something is an error, the function raises the error named.

```python
from datetime import date
import cadence

holidays = cadence.load_holidays("data/holidays.txt")
cadence.expand("monthly on business day -1; closed: previous", date(2025, 1, 1), date(2025, 12, 31), holidays)
```

## 1. API

- `cadence.expand(rule, start, end, holidays=()) -> list[date]` returns the dates of the
  rule's occurrences that fall between `start` and `end`, both inclusive, sorted, without
  duplicates. `holidays` is a `cadence.Holidays` (section 6) or any iterable of `date`s.
  If `start` is after `end` the result is empty.
- `cadence.RuleError` (a subclass of `ValueError`) is raised for any rule that does not
  follow this document.
- `cadence.load_holidays(path) -> Holidays` reads a holiday file (section 6).

## 2. Syntax

Rules are case-insensitive. A rule is one or more *clauses* separated by `;`. Whitespace
around clauses is ignored, and inside a clause any run of spaces counts as one space. An
empty clause (for example from a trailing `;`) is an error.

The first clause is the *pattern* (section 3). Every later clause is an *option*
(section 4). Each option may be given at most once, in any order.

Numbers are written in decimal digits. Dates are written `YYYY-MM-DD` and must be real
dates. Weekdays are written either as three letters (`mon`, `tue`, `wed`, `thu`, `fri`,
`sat`, `sun`) or in full (`monday` ... `sunday`). Months are written as three letters
(`jan` ... `dec`).

## 3. Patterns

| pattern                                 | meaning                                   |
|-----------------------------------------|-------------------------------------------|
| `daily`                                 | same as `every 1 day`                     |
| `every N days`                          | every N-th day                            |
| `every business day`                    | every business day (section 5)            |
| `weekly [on WEEKDAYS]`                  | same as `every 1 week [on WEEKDAYS]`      |
| `every N weeks [on WEEKDAYS]`           | on the given weekdays of every N-th week  |
| `monthly [on MONTH-DAYS]`               | same as `every 1 month [on MONTH-DAYS]`   |
| `every N months [on MONTH-DAYS]`        | on the given days of every N-th month     |
| `yearly [on YEAR-DAYS]`                 | same as `every 1 year [on YEAR-DAYS]`     |
| `every N years [on YEAR-DAYS]`          | on the given days of every N-th year      |

`N` is at least 1. The unit may be written singular or plural whatever `N` is (`every 1
days` and `every 2 week` are fine). `daily` and `every N days` take no `on` part, and
neither does `every business day`; giving one is an error.

### 3.1 The anchor and periods

Every rule has an *anchor* date: the date of the `from` option, or `start` if there is no
`from`. Nothing is ever scheduled before the anchor.

The anchor also fixes which periods count. For `every N days` the scheduled dates are the
anchor, the anchor plus N days, plus 2N days and so on. For the other units the calendar
is split into periods: weeks (Monday to Sunday), calendar months or calendar years. The
period containing the anchor is period 0, and the rule uses periods 0, N, 2N, ... In
period 0, dates before the anchor are dropped, so `every 2 weeks on mon, fri` anchored on
a Wednesday first happens on that week's Friday.

### 3.2 WEEKDAYS

A comma-separated list of weekdays, such as `on mon, thu`. Without `on`, the rule uses the
anchor's weekday.

### 3.3 MONTH-DAYS

A comma-separated list where each item is one of:

- `day D` with D from 1 to 31: the D-th day of the month. A month too short for D uses
  its last day instead, so `day 31` is April 30.
- `day -D` with D from 1 to 31: the D-th day counted from the end, `day -1` being the
  last day. A month too short uses its first day instead.
- `ORD WEEKDAY` where ORD is `1st`, `2nd`, `3rd`, `4th`, `5th` or `last`, such as
  `2nd tue` or `last fri`. Unlike `day D`, this is never moved: a month without a fifth
  Tuesday has no `5th tue` occurrence.
- `business day B` with B at least 1: the B-th business day of the month, and
  `business day -B`: the B-th business day counted from the end. A month with fewer than
  B business days has no such occurrence.

Without `on`, the rule uses `day D` where D is the anchor's day of the month, so
`monthly; from 2024-01-31` gives January 31, February 29, March 31, April 30, ...
Two items that give the same date in a month give one occurrence.

### 3.4 YEAR-DAYS

A comma-separated list of `MON D` items, such as `on mar 31, sep 30`. D must exist in that
month in a leap year, so `feb 29` is allowed but `feb 30` and `apr 31` are errors. In a
year that is not a leap year, `feb 29` means February 28. Without `on`, the rule uses the
anchor's month and day.

## 4. Options

- `from DATE`: sets the anchor (3.1).
- `until DATE`: no occurrence is scheduled after DATE. It applies to the *scheduled* date,
  before section 5 may move it.
- `count C` with C at least 1: the rule has only its first C occurrences. They are counted
  from the anchor, after `except` and section 5 have been applied, and do not depend on
  `start` and `end`: asking for a window in the middle of the rule's life returns only
  those of the first C occurrences that fall in it.
- `except DATE, DATE, ...`: these scheduled dates are left out. Like `until`, this looks at
  the scheduled date, before section 5.
- `closed: keep`, `closed: skip`, `closed: next` or `closed: previous`: what happens to an
  occurrence scheduled on a closed day (section 5). The default is `keep`.

`until` and `count` cannot both be given. An `until` date before the `from` date is an
error. Any other clause is an error.

## 5. Business days and closed days

A *closed* day is a Saturday, a Sunday or a holiday. Every other day is a *business day*.

When an occurrence is scheduled on a closed day:

- `keep` leaves it where it is;
- `skip` drops it;
- `next` moves it to the first business day after it;
- `previous` moves it to the last business day before it.

A moved occurrence may land in another month or year, before the anchor, after `until`,
or on the same date as another occurrence; occurrences that end up on the same date count
as one. Whether an occurrence is returned depends on the date it ends up on: an occurrence
scheduled on Saturday 31 May 2025 and moved to Monday 2 June is returned for a window that
starts on June 1, and not for one that ends on May 31.

## 6. Holidays

`cadence.Holidays` is a set of holidays; `day in holidays` tells whether `day` is one.
`Holidays(dates)` makes one from an iterable of dates. `load_holidays(path)` reads a
UTF-8 holiday file:

```
# Office holidays
2024-12-24..2024-12-26   Christmas break
*-01-01                  New Year's Day
2025-04-18               Good Friday   # moves every year
```

Everything from a `#` to the end of the line is a comment. Each line, after removing the
comment and surrounding whitespace, is blank or starts with one of:

- `YYYY-MM-DD`: that date;
- `YYYY-MM-DD..YYYY-MM-DD`: every date from the first to the second, inclusive. The
  second date must not be before the first;
- `*-MM-DD`: that month and day in every year. `*-02-29` is a holiday only in leap years.

Anything after the date, separated from it by whitespace, is the holiday's name and is
ignored. An every-year holiday that falls on a Saturday is also observed on the Friday
before it, and one that falls on a Sunday is also observed on the Monday after it; both
the day itself and the observed day are holidays. This does not apply to dates written
with a year.

Any other line raises `cadence.HolidayFileError` (a subclass of `ValueError`) whose
`line` attribute is the 1-based number of the offending line.
