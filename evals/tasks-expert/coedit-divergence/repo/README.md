# coedit

A text document that several people edit at the same time, each on their own copy (a
*replica*). A replica applies its owner's edits at once and sends them to the others as
*ops*; nobody waits for anybody.

```python
from coedit import Replica

ann, bob = Replica("ann"), Replica("bob")
op = ann.insert(0, "h")     # ann types; her copy changes now
bob.apply(op)               # ...and bob's when the op reaches him
bob.text()                  # "h"
```

## Ops

Every character ever typed has an id `(counter, site)`, unique for all time.

- `Insert(id, after, char)`: a new character, typed directly after the character `after`
  (`None`: at the very start).
- `Delete(target)`: remove that character. It stops showing but is not forgotten, since
  other characters may have been typed after it.

## The order of the text

The inserts form a tree: each character is a child of the one it was typed after, and
characters typed at the very start are children of the start. The text is that tree read
depth-first: a character, then everything typed after it, before its parent's next child.
Children of the same parent come **newest first: higher counter first, and for equal
counters the higher site (compared as strings) first**. Deleted characters keep their place
in the tree and are left out of the text.

That is the whole definition. Two replicas that have applied the same set of ops show the
same text, whatever order the ops came in.

## What the network does

- Ops arrive in any order. An op can arrive **before** the op it depends on: an insert
  after a character that hasn't arrived yet, or a delete of one. Such an op takes effect
  when what it depends on arrives.
- Ops can arrive more than once. A repeat changes nothing.
- Every op reaches every replica eventually, the sender's own included (applying your own
  op again changes nothing).

## Ids

A replica numbers its own characters so that a newly typed one is newer than everything it
has seen, which is what makes `insert(index, char)` put the character at `index` in its own
text straight away.

Nothing else may be assumed about ids. Ops also come from other clients (the mobile app, an
importer for old documents) that number characters their own way: **a character's counter
can be lower than that of the character it was typed after.** Ids are unique, and that is
all. The order of the text is defined by the tree above for any ids.

## A replica's own edits

`insert(index, char)` makes `char` the character at `index` of the replica's own `text()`
and returns the op; `delete(index)` removes the character at `index` of `text()` and
returns the op. `index` counts the characters that show, not the deleted ones.

## Tests

```
python -m pytest -q
```
