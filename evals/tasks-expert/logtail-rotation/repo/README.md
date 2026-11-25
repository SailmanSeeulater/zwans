# logtail

Follow log files by name, like `tail -F`: a `Follower` hands you each line a program
writes to its log, and keeps doing so when the log is rotated or truncated.

```python
from logtail import FakeFS, Follower

fs = FakeFS()
app = fs.writer("app.log")          # the program's open log file
follower = Follower(fs, "app.log")

app.write("started\nlistening on :80")
follower.poll()                     # ['started']
app.write("80\n")
follower.poll()                     # ['listening on :8080']
```

From the shell: `python -m logtail [-n] [-s SECONDS] FILE...` follows real files (`-n`
skips what they already hold).

## The pieces

- `logtail/follower.py`: `Follower`, which follows one path.
- `logtail/tail.py`: `Tail`, several followers polled together, and the command line
  (`--grep REGEX`, `--json`).
- `logtail/fakefs.py`: `FakeFS`, an in-memory file system with inodes, for tests. A path
  names an inode; `rename` moves the name and keeps the inode, `create` gives a path a
  new empty inode, and anything holding a file open (a `Writer` from `fs.writer(path)`, a
  `Handle` from `fs.open(path)`) stays on its inode whatever happens to the path. Offsets
  and sizes count characters. `fs.chars_read` counts the characters handles have read.
- `logtail/osfs.py`: the same reading interface over real files.
- `logtail/rotate.py`: what logrotate does, on a `FakeFS`: `rotate` (rename to `.1`, then
  optionally create a new log) and `copytruncate` (copy to `.1`, then empty the log).

A follower only uses `fs.stat(path)` (an inode number and a size), `fs.open(path)` and the
handle's `inode`, `size()`, `read(offset, size)` and `close()`.

## Follower

```python
Follower(fs, path, *, max_line=65536, chunk_size=65536, from_end=False, on_line=None)
```

`poll()` returns the lines that have become available since the previous poll, in order,
each without its newline. With `on_line`, each line is passed to `on_line(line)` instead
and `poll()` returns an empty list. Nothing happens between polls: everything below is
decided when `poll()` looks at the files.

The follower starts on the file at `path` when it is created, from its beginning, or from
its end as it is then with `from_end=True`. If there is no file at `path` yet, it waits,
and reads the first file that appears there from its beginning.

### Lines

- A line is complete when its `\n` has been written. Every complete line is delivered
  exactly once, in the order it was written.
- Text after the last newline of a file is an unfinished line: the follower holds it, and
  delivers it with the rest of the line once the newline arrives, however many writes and
  polls that takes.
- No line is longer than `max_line` characters: when a line, finished or not, grows longer
  than that, its first `max_line` characters are delivered as one line and the rest
  carries on as the line. So a line of 10 characters with `max_line=4` is delivered as
  `abcd`, `efgh`, `ij`, however it was written; an empty line is delivered as `""`.

### Rotation

At each poll the follower checks which file `path` names now. If it names a different file
(a different inode) from the one being followed, the log has been rotated (renamed away
and recreated, deleted and recreated, or another file moved onto the path). The follower
then, in this order:

1. reads the rest of the old file, including whatever was written to it after the rename
   (a program keeps writing to its old file until it reopens its log);
2. delivers the old file's unfinished line, if it holds one, as a line of its own;
3. moves to the new file and reads it from its beginning, even if it read that file
   before under another name.

After that it no longer reads the old file; anything written to it later is not delivered.

While there is no file at `path` at all, the follower keeps reading the file it has, since
the program may still be writing to it, and moves on when a new file appears at `path`.

A file that appears at `path` and is rotated away again between two polls is never seen by
the follower; its lines are not delivered.

### Truncation

When the followed file is smaller than the part of it already read, it has been truncated
(by `copytruncate`, for instance): the follower delivers the unfinished line it holds, if
any, as a line of its own, and reads the file again from its beginning. A file that was
truncated and has grown back past that point by the next poll can't be told apart from
one that just grew, and the follower reads on from where it was. Lines written after the
last poll and truncated away before the next are not delivered.

### Cost

A follower's memory doesn't grow with the file or its lines: it reads at most
`chunk_size` characters per `read` call and holds at most `max_line` characters of an
unfinished line. (With `on_line`, it doesn't collect lines either.) It reads each part of a
file once: a poll reads only the text added since the last one (plus, after a rotation,
the rest of the old file and the new file from its beginning, and after a truncation the
file from its beginning).

## Tests

```
python -m pytest -q
```
