# logq

Search log files with a small pattern language: a subset of Python's regular expressions
that behaves exactly like `re` on everything it accepts, and that is cheap to run on any
line, however long, whatever the pattern.

```
$ python -m logq 'user=\w+ (login|logout)' app.log
2024-05-01 10:22:03 user=ana login
2024-05-01 10:31:40 user=bo logout
```

```python
import logq

pattern = logq.compile(r"(\d+\.){3}\d+")
pattern.search("from 10.0.0.12 port 22")    # (5, 14)
pattern.fullmatch("10.0.0.12")              # True
```

## Patterns

| syntax | matches |
| --- | --- |
| `a` | that character (any character not listed below) |
| `.` | any character except a newline |
| `[abc]`, `[a-z0-9_]` | one character from the class; `a-z` is a range |
| `[^abc]` | one character not in the class |
| `\d`, `\w` | a digit `[0-9]`; a word character `[a-zA-Z0-9_]` (also inside classes) |
| `\.`, `\*`, `\[`, ... | the escaped character itself: any of `. ^ $ * + ? ( ) [ ] { } \| \ - /` |
| `xy` | `x` then `y` |
| `x\|y` | `x` or `y` (either side may be empty) |
| `(x)` | a group, for alternation and repeats; groups don't capture |
| `^`, `$` | the start, the end of the text |
| `x*`, `x+`, `x?` | 0 or more, 1 or more, 0 or 1 of `x` |
| `x{m}`, `x{m,}`, `x{m,n}` | exactly m, at least m, from m to n of `x` (counts up to 1000) |

Inside a class, `-` is a plain character when it comes first or last, and `\` escapes the
next character. The special characters `. ^ $ * + ? ( ) [ ] { } | \` must be escaped to be
matched literally anywhere outside a class, including `]` and `}`.

`compile` raises `logq.PatternError` for anything else, in particular:

- a quantifier with nothing before it, or right after another quantifier (`*a`, `a**`,
  `a+?`, `a{2}*`);
- a quantifier on something that can match the empty string, such as `(a?)*`, `(a|)+`,
  `()*`, `(^)?` or `(b{0}){2}`;
- an empty class `[]`, a range that runs backwards like `[z-a]`, a count with its minimum
  above its maximum like `a{3,2}`, an unknown escape like `\n`, or an unbalanced bracket.

Patterns and text are ASCII, and a log line never contains a newline.

## Matching

`pattern.search(text)` returns the `(start, end)` span of the first match in the text, or
`None`; `pattern.fullmatch(text)` returns whether the whole text matches. Both behave
exactly as Python's `re.search(...).span()` and `re.fullmatch(...)` do for the same
pattern and text: the match starts as far left as possible; from there, alternatives are
tried left to right and repeats take as many as they can, the first combination that
leads to a match winning. So `a|ab` finds `a` in `ab`, and `(a|ab)(c|bcd)` matches all of
`abcd`.

## What a match costs

Users paste in patterns we've never seen and run them over huge files, so the cost of a
match can't depend on how unlucky the pattern is.

A **step** is one test of one character of the text against one character item of the
pattern: a literal, `.`, a class, `\d` or `\w`. The pattern's **size** is the number of
character items it has, counting each copy a repeat makes: `x*` and `x?` count `x` once,
`x{m}` counts it m times, `x{m,n}` n times and `x{m,}` m + 1 times (so `x+` counts it
twice), and repeats inside repeats multiply. For example `(ab|c){2,3}d` has size 10.
`pattern.size` gives it.

`search` and `fullmatch` take an optional `meter`: any object with a `step()` method,
which the matcher calls once for every step. `logq.Meter(limit)` counts them in `.steps`
and raises `StepLimitExceeded` when a match goes over its limit (that's what `--max-steps`
uses).

**On a text of length n, one call to `search` or `fullmatch` takes at most
`2 * size * (n + 1)` steps**, whatever the pattern and the text.

Lines can be long: the tool has to cope with lines of 100,000 characters.

## Command line

```
python -m logq PATTERN [FILE ...] [-o] [-c] [--max-steps N]
```

Prints each line with a match (prefixed with `file:line:` when there are several files).
`-o` prints only the matched part, `-c` only the number of matching lines. With
`--max-steps`, a line that takes more steps is skipped with a warning on stderr. Exit
status 0 if anything matched, 1 if nothing did, 2 for a bad pattern. With no files, it
reads standard input.

## Tests

```
python -m pytest -q
```
