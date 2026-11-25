# linediff

Line diffs, unified hunks and patches, as a library and a small command-line tool.

```python
from linediff import diff, unified, apply

old = ["a", "b", "c", "d"]
new = ["a", "c", "d", "e"]

diff(old, new)
# [Op('keep', 0, 1, 0, 1), Op('delete', 1, 2, 1, 1), Op('keep', 2, 4, 1, 3),
#  Op('insert', 4, 4, 3, 4)]

patch = unified(old, new, context=1)
apply(patch, old) == new   # True
```

## The edit script

`diff(old, new)` takes two sequences of lines and returns the edit script that turns `old`
into `new`, as a list of `Op(tag, old_start, old_end, new_start, new_end)` runs. Each run
covers `old[old_start:old_end]` and `new[new_start:new_end]`:

- `keep`: the same number of lines on both sides, equal line for line;
- `delete`: lines of `old` only (`new_start == new_end`);
- `insert`: lines of `new` only (`old_start == old_end`).

The runs come in order, each starting where the last one ended, and together cover both
sequences from start to end. Two runs in a row never have the same tag.

**The script is minimal**: no script deletes and inserts fewer lines in all.

**Which minimal script.** Often several scripts are equally short. `diff` returns the one
that deletes as early and inserts as late as it can. To be exact: for each line of `old`,
count the lines of `new` the script has gone past (kept or inserted) before it gets to that
line. Among the minimal scripts there is always one whose count is the smallest possible
for every line of `old` at once, and that is the one `diff` returns. One consequence is
that within a change, the deleted lines always come before the inserted ones. Some
examples:

| old | new | script |
| --- | --- | --- |
| `a b` | `c d` | delete `a b`, insert `c d` |
| `x y x` | `x` | delete the first `x` and `y`, keep the last `x` |
| `x` | `x x` | keep `x`, insert the second `x` |
| `a b` | `b a` | delete `a`, keep `b`, insert `a` |

Lines can be any objects that support `==`; they don't have to be strings and they don't
have to be hashable. `diff` only ever compares two lines with `==`: it never hashes,
sorts or otherwise looks inside them.

## Big files

The files people diff are often long (tens of thousands of lines) with only a handful of
changes, and `diff` has to handle them in time and memory that grow with the size of the
files and the number of changes, never with the product of the two sizes.

- **Comparisons.** Every `==` between two lines counts as one comparison. Diffing N lines
  against M lines whose minimal script deletes and inserts D lines in all takes at most
  `4 * (N + M + 1) * (D + 1)` comparisons.
- **Memory.** While `diff` runs, the memory it allocates (as `tracemalloc` measures it:
  the peak, including the script it returns, not counting the two input sequences) stays
  under `400 * (N + M)` bytes plus 1 MiB.

## Unified diffs

`unified(old, new, context=3, old_name="old", new_name="new")` writes the script as a
unified diff. Identical inputs give `""`. Otherwise the text looks like this (for
`old = ["a", "b", "c"]` and `new = ["a", "c", "e"]`):

```
--- old
+++ new
@@ -1,3 +1,3 @@
 a
-b
 c
+e
```

- Two header lines, `--- <old_name>` and `+++ <new_name>`, then the hunks in order.
- Each hunk holds one or more changes with up to `context` kept lines before and after
  them. Two changes with at most `2 * context` kept lines between them go in the same
  hunk, with all of those lines; otherwise they get hunks of their own.
- A hunk starts with `@@ -<start>,<count> +<start>,<count> @@`, the old and the new range
  it covers. `start` is the 1-based number of the range's first line; for a range of no
  lines it is the number of the line before it (0 at the top of the file). The count is
  always written, even when it is 1.
- Then one line per line of the hunk, in script order: `" "` and the text for a kept line,
  `"-"` for a deleted line and `"+"` for an inserted one. Every line ends in `"\n"`.

## Patching

`apply(patch, old)` applies a unified diff to a list of lines and returns the new list.
Each hunk must find its kept and deleted lines in `old` exactly where its header says;
otherwise, or if the patch is malformed, it raises `PatchError`. For any `old`, `new` and
`context >= 0`, `apply(unified(old, new, context), old) == new`. `parse(patch)` returns the
hunks without applying them; it accepts headers with or without the counts.

## Command line

```
python -m linediff OLD NEW [-U N]       # unified diff of two files; exit 1 if they differ
python -m linediff --apply PATCH FILE   # FILE with PATCH applied, on stdout
```

Files are read as UTF-8 and split into lines on `"\n"`; a newline at the very end of a
file doesn't make an extra empty line. A patch that doesn't fit exits with status 2.

## Tests

```
python -m pytest -q
```
