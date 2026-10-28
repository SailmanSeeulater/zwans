"""python -m notes.cli (list | search WORDS | export FOLDER)"""

import sys
from pathlib import Path

from notes.export import export_markdown
from notes.search import search
from notes.storage import Store


def main(argv: list[str]) -> int:
    store = Store(Path.home() / ".notes")
    if argv[:1] == ["list"]:
        for note in store.all():
            print(note.title)
    elif argv[:1] == ["search"]:
        print("\n".join(search(store, " ".join(argv[1:]))))
    elif argv[:1] == ["export"] and len(argv) == 2:
        print(f"exported {export_markdown(store, Path(argv[1]))} notes")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
