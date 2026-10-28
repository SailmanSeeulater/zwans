# Strata configuration format

Strata is the configuration format our services use. A configuration is one text file
(UTF-8) that may include others. `strata.load(path, env=None)` reads it and returns the
result as nested Python dicts. This document is the complete definition of the format;
where it says something is an error, `load` raises `strata.ConfigError`.

```
# service.st
[server]
host = 0.0.0.0
port = 8080
url = "http://${.host}:${.port}/"

[server.tls]
enabled = false

@include "logging.st"
```

## 1. Lines

A file is read line by line. Leading and trailing whitespace is removed from every line
first. A line is then exactly one of:

- **blank**: nothing left. Ignored.
- **comment**: starts with `#` or `;`. Ignored.
- **section header**: starts with `[` (section 3).
- **directive**: starts with `@` (section 7).
- **assignment**: anything else (section 4).

A line that does not fit the form it starts with is a syntax error. There are no
continuation lines.

## 2. Names and paths

A *name* is a letter or `_`, followed by any number of letters, digits, `_` and `-`
(`[A-Za-z_][A-Za-z0-9_-]*`, ASCII only). Names are case-sensitive. A *path* is one or more
names joined by single dots, such as `server.tls.enabled`. No whitespace is allowed inside
a path.

## 3. Sections

`[path]` makes the section at `path` the *current section*. Whitespace just inside the
brackets is allowed: `[ server.tls ]`. `[]` makes the root the current section again.
Nothing but a trailing comment (section 5.5) may follow the closing `]`.

Every file starts with its *base* section as the current section. For the file passed to
`load` the base is the root; for included files see section 7.1. A header's path is
relative to the file's base, so in a file whose base is the root, `[server.tls]` means
`server.tls`.

A header creates its section (and any missing parents) as an empty table if it does not
exist yet, so an empty section still appears in the result as `{}`. A section may be
opened any number of times; later keys are added to what is already there.

## 4. Assignments

An assignment is `target OP value`, where `target` is a path, `OP` is one of `=`, `+=` or
`?=`, and whitespace around `OP` is optional (`a=1`, `a = 1`). The target is relative to
the current section: in `[server]`, `tls.port = 443` sets `server.tls.port`, creating the
table `server.tls` if needed.

- `=` sets the value, replacing any value already there.
- `?=` sets the value only if the target has no value yet at this point of the load.
  Assignments and includes that come later can still change it.
- `+=` appends:
  - if the target has no value yet, it is set to a list: a copy of the value if the value
    is a list, otherwise a one-item list holding the value;
  - if the target holds a list, a list value is concatenated onto it and any other value
    is appended to it as one item;
  - if the target holds anything else, it is an error.

  `+=` runs while the files are read, before any reference is resolved, so whether a
  value is a list is decided by how it was written: only a value written as `[...]`, or a
  list built by `+=`, is a list. A value that is a reference is never a list here, even if
  it resolves to one later; `tags += ${defaults.tags}` appends a single item.

A table and a value can never share a path. It is an error to assign a value where a table
exists (`server = 1` once `[server]` was opened), and an error to use a value as a table
(`a = 1` followed by `a.b = 2`, or by the header `[a.b]`).

## 5. Values

The value is the text after `OP`, with surrounding whitespace removed.

### 5.1 Bare values

A value that does not start with `"`, `'` or `[` is bare.

- An empty value is the empty string `""`.
- `true` and `false` (lower case only) are booleans. `True`, `FALSE` and so on are strings.
- An *integer* is an optional `-` followed by decimal digits, where single underscores may
  separate digits (`1_000_000`). An integer with a leading zero, like `007` or `-05`,
  is a string, not an integer; `0` and `-0` themselves are the integer 0. Text like `1_`,
  `_1`, `1__0` or `+5` is a string.
- Anything else is a string. Interpolation (section 6) applies to bare strings.

The type is decided from the text as written, before interpolation, with one exception
given in section 6.2.

### 5.2 Double-quoted strings

`"..."` is a string. Inside it, `\\`, `\"`, `\n`, `\t` and `\$` are escapes for a backslash,
a double quote, a newline, a tab and a literal `$`; any other backslash sequence is an
error. Interpolation applies, except that an escaped `\$` is never the start of a
reference. A double-quoted value is always a string, even `"42"` or `"true"`.

### 5.3 Single-quoted strings

`'...'` is a string taken literally: no escapes and no interpolation. It cannot contain a
single quote.

### 5.4 Lists

`[item, item, ...]` is a list. Items are separated by commas; whitespace around items is
ignored; a single trailing comma is allowed (`[a, b,]`), and `[]` is the empty list. An
empty item anywhere else (`[a,,b]`, `[,]`) is an error. Each item is a bare value,
a double-quoted string or a single-quoted string, with the same rules as above; commas and
`]` inside quotes belong to the item. Lists cannot be nested: an item starting with `[`
is an error. Nothing but a trailing comment may follow the closing `]`.

### 5.5 Trailing comments

Outside quotes, a `#` that comes right after a space or tab starts a comment that runs to
the end of the line; it and the whitespace before it are not part of the value. A `#` not
preceded by whitespace is an ordinary character: `color = a#b` is the string `a#b`. This
also applies to section headers, directives and list items. After a closing quote only
whitespace and a trailing comment may follow; anything else is an error.

## 6. Interpolation

### 6.1 References

A *reference* is `${...}` inside a bare or double-quoted string:

- `${path}` refers to the value at `path`, counted from the root.
- `${.path}` refers to `path` relative to the section that was current where the
  assignment was written. For `tls.url = ${.host}` written under `[server]` that is
  `server.host`, not `server.tls.host`.
- `${env:NAME}` is the environment variable `NAME`; `${env:NAME:-fallback}` uses the
  literal text `fallback` (which may be empty) when `NAME` is not set. Without a fallback
  an unset variable is an error. The environment is the `env` mapping passed to `load`,
  or `os.environ` when `env` is `None`.

`$$` is a literal `$`. A `$` followed by anything other than `{` or `$` is a literal `$`.
An unterminated `${` is an error.

### 6.2 What a reference produces

If a bare value (or a bare list item) consists of exactly one reference and nothing else,
it takes the referenced value as it is, whatever its type: `port = ${defaults.port}` is an
integer if `defaults.port` is one. A list taken this way is copied. A bare list item that
refers to a list or a table is an error, because lists cannot be nested.

In every other case the referenced value is turned into text and spliced in: strings as
they are, integers in decimal, booleans as `true` and `false`, environment variables as
they are. Splicing a list or a table into text is an error. A double-quoted string is
always a string, so `"${defaults.port}"` is the string `"8080"`.

### 6.3 When references are resolved

References are resolved after every file has been read, against the final values. So in

```
[paths]
root = /srv
logs = ${.root}/logs
[paths]
root = /opt
```

`paths.logs` is `/opt/logs`. A referenced value may itself contain references; they are
resolved first. A reference to a path that has no value, or that holds a table, is an
error unless the reference is a whole bare value (6.2), where a table is copied in as a
nested dict. A chain of references that leads back to itself is an error whose message
contains the word `cycle`.

## 7. Directives

A directive line is `@name` followed by its argument. Unknown directives are errors.

### 7.1 `@include "file"`

Reads another file at this point of the load, as if its lines were written here, with
these rules:

- The file name must be a double-quoted string with no escapes or interpolation. A
  relative name is relative to the directory of the file containing the directive.
- The included file's base section is the section that is current at the `@include`
  line. Its headers are relative to that base, and its `[]` returns to that base.
- When the included file ends, the including file carries on with the current section it
  had before the `@include`. Section headers in an included file never change the
  including file's current section.
- A file that includes itself, directly or through other files, is an error whose message
  contains the word `cycle`. Including the same file twice from different places is
  fine; it is simply read twice.
- A missing file is an error.

`@include? "file"` is the same, except that a missing file is silently skipped. Other
errors in the file are still errors.

### 7.2 `@unset path`

Removes the value or table at `path`, relative to the current section. Removing something
that does not exist is not an error.

## 8. Errors

`strata.ConfigError` is a subclass of `Exception` with two attributes:

- `file`: the `pathlib.Path` of the file containing the offending line, or `None`.
- `line`: the 1-based line number of that line in that file, or `None`.

Syntax errors and errors from applying an assignment, header or directive point at that
line. An error while resolving a reference (a missing path, a missing environment
variable, a list spliced into text, a cycle) points at the assignment whose value contains
the reference that failed. A missing file passed to `load` has `line` set to `None`, and
an `@include` of a missing file points at the `@include` line.

## 9. The result

`load` returns a dict for the root. Tables are dicts, strings are `str`, integers `int`,
booleans `bool` and lists `list`. Values are fully resolved: no references remain.
