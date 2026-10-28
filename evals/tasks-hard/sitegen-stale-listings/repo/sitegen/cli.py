"""Command line: sitegen build | serve | new."""

import argparse
import sys
from datetime import date
from pathlib import Path

from sitegen.builder import Builder
from sitegen.config import ConfigError
from sitegen.content import ContentError
from sitegen.frontmatter import FrontMatterError
from sitegen.slugify import slugify
from sitegen.templates import TemplateError


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sitegen")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build the site into public/")
    build.add_argument("root", nargs="?", default=".")
    build.add_argument("--clean", action="store_true", help="delete public/ first")
    build.add_argument("--drafts", action="store_true", help="include drafts")
    build.add_argument("--quiet", action="store_true", help="only print the summary line")

    serve = commands.add_parser("serve", help="build, serve and rebuild on changes")
    serve.add_argument("root", nargs="?", default=".")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--drafts", action="store_true")

    new = commands.add_parser("new", help="start a new post")
    new.add_argument("title")
    new.add_argument("--root", default=".")
    new.add_argument("--tags", default="", help="comma-separated")
    return parser.parse_args(argv)


def new_post(root: Path, title: str, tags: str, today: date | None = None) -> Path:
    today = today or date.today()
    path = root / "content" / "posts" / f"{slugify(title)}.md"
    if path.exists():
        raise ContentError(f"{path} already exists")
    tag_list = ", ".join(t.strip() for t in tags.split(",") if t.strip())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\ndate: {today.isoformat()}\ntags: [{tag_list}]\ndraft: true\n---\n\n",
        encoding="utf-8",
    )
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.command == "build":
            report = Builder(Path(args.root), drafts=args.drafts).build(clean=args.clean)
            print(report.describe())
            if not args.quiet:
                for path in report.written:
                    print(f"  + {path}")
                for path in report.removed:
                    print(f"  - {path}")
        elif args.command == "serve":
            from sitegen.serve import serve

            serve(Path(args.root), port=args.port, drafts=args.drafts)
        elif args.command == "new":
            print(new_post(Path(args.root), args.title, args.tags))
    except (ConfigError, ContentError, FrontMatterError, TemplateError) as exc:
        print(f"sitegen: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
