import argparse
import sys

from kvstore.base import KeyNotFound
from kvstore.factory import open_store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kvstore")
    parser.add_argument("--store", required=True, help="a store URL, like json://data.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("get").add_argument("key")
    setter = commands.add_parser("set")
    setter.add_argument("key")
    setter.add_argument("value")
    commands.add_parser("del").add_argument("key")
    commands.add_parser("keys").add_argument("prefix", nargs="?", default="")
    args = parser.parse_args(argv)

    with open_store(args.store) as store:
        try:
            if args.command == "get":
                print(store.get(args.key))
            elif args.command == "set":
                store.set(args.key, args.value)
            elif args.command == "del":
                store.delete(args.key)
            elif args.command == "keys":
                for key in store.keys(args.prefix):
                    print(key)
        except KeyNotFound:
            print(f"no such key: {args.key}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
