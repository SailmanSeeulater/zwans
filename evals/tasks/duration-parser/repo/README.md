# timer

Small helpers for reminders and countdowns.

## Durations

`timer.durations.parse_duration(text: str) -> int` turns a human-written duration into a
whole number of seconds. `format_duration(seconds: int) -> str` goes the other way.

A duration is one or more *components*. Each component is a whole number (digits only)
followed directly by a unit:

| unit | meaning | seconds |
|------|---------|---------|
| `d`  | days    | 86400   |
| `h`  | hours   | 3600    |
| `m`  | minutes | 60      |
| `s`  | seconds | 1       |

Rules:

- Units are case-insensitive: `1H30M` is the same as `1h30m`.
- Components must come largest unit first, and each unit may appear at most once.
  `1h30m` is fine; `30m1h` and `1h1h` are not.
- Components may be separated by spaces, and leading or trailing whitespace is ignored:
  `1h 30m` and `  2d4h ` are fine. There may be no space between a number and its unit.
- Values do not have to be normalised: `90m` is 5400 seconds and `0s` is 0.
- Anything else is invalid and raises `timer.durations.DurationError` (a subclass of
  `ValueError`). That includes the empty string, a number without a unit (`90`), a unit
  without a number (`h`), unknown units (`3w`), signs (`-5m`, `+5m`), decimals (`1.5h`)
  and stray characters (`1h, 30m`).

Examples:

```python
parse_duration("1h30m")   # 5400
parse_duration("2d 4h")   # 187200
parse_duration("45s")     # 45
format_duration(5400)     # "1h30m"
```
