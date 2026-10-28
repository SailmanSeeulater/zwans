import json
import re

from conftest import DATA
from markbook import store
from markbook.collection import Collection
from markbook.html_format import import_html, parse_html


def firefox() -> str:
    return (DATA / "firefox.html").read_text("utf-8")


def as_saved(collection: Collection, tmp_path) -> dict[str, list[str]]:
    """title -> sorted tags, as written to a file."""
    path = tmp_path / "saved.json"
    store.save(collection, path)
    bookmarks = json.loads(path.read_text("utf-8"))["bookmarks"]
    for b in bookmarks:
        assert len(set(b["tags"])) == len(b["tags"]), b
    return {b["title"]: sorted(b["tags"]) for b in bookmarks}


def test_a_browser_export_is_parsed() -> None:
    found = [(i.url, i.title, i.added) for i in parse_html(firefox())]
    assert found == [
        ("https://www.wikipedia.org/", "Wikipedia", "2024-01-01"),
        ("javascript:alert('hi')", "A bookmarklet", "2024-01-01"),
        ("https://docs.python.org/3/", "Python & friends", "2024-02-01"),
        ("https://scikit-learn.org/", "scikit-learn", "2024-03-01"),
        ("https://www.seriouseats.com/", "Serious Eats", ""),
    ]


def test_importing_skips_what_cannot_be_kept() -> None:
    collection = Collection()
    collection.add("https://www.seriouseats.com", "Already here")
    result = import_html(collection, firefox())
    assert [b.title for b in result.added] == ["Wikipedia", "Python & friends", "scikit-learn"]
    assert result.skipped == ["javascript:alert('hi')", "https://www.seriouseats.com/"]


def test_imported_folders_and_tags_become_tags(tmp_path) -> None:
    collection = Collection()
    import_html(collection, firefox())
    assert as_saved(collection, tmp_path) == {
        "Wikipedia": [],
        "Python & friends": ["dev", "reference"],
        "scikit-learn": ["dev", "machine-learning", "ml", "python"],
        "Serious Eats": ["recipes"],
    }


def test_export_writes_a_browser_bookmark_file(cli) -> None:
    cli(
        "add",
        "https://docs.python.org/3/",
        "--title",
        "Python <docs>",
        "--tag",
        "dev",
        "--tag",
        "python",
    )
    cli("add", "https://www.gutenberg.org/", "--title", "Gutenberg")
    code, text, _ = cli("export")
    assert text.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    [python] = [line for line in text.splitlines() if "docs.python.org" in line]
    assert 'HREF="https://docs.python.org/3/"' in python
    assert 'ADD_DATE="1772323200"' in python
    assert "Python &lt;docs&gt;</A>" in python
    tags = re.search(r'TAGS="([^"]*)"', python)
    assert tags is not None
    assert sorted(tag.strip() for tag in tags.group(1).split(",")) == ["dev", "python"]


def test_export_then_import_gives_the_same_bookmarks(cli, tmp_path) -> None:
    cli(
        "add",
        "https://docs.python.org/3/",
        "--title",
        "Python docs",
        "--tag",
        "dev",
        "--tag",
        "python",
    )
    cli(
        "add",
        "https://docs.pytest.org/",
        "--title",
        "pytest",
        "--tag",
        "python",
        "--tag",
        "testing",
        "--star",
    )
    cli("add", "https://www.gutenberg.org/", "--title", "Gutenberg")
    cli(
        "add",
        "https://www.seriouseats.com/",
        "--title",
        "Serious Eats",
        "--tag",
        "home",
        "--tag",
        "Cooking & Baking",
    )
    exported = tmp_path / "export.html"
    exported.write_text(cli("export")[1], "utf-8")
    original = json.loads(cli.path.read_text("utf-8"))["bookmarks"]

    cli.path = tmp_path / "again.json"
    assert cli("import", str(exported))[0] == 0
    again = json.loads(cli.path.read_text("utf-8"))["bookmarks"]
    key = lambda b: (b["url"], b["title"], sorted(b["tags"]), b["added"])  # noqa: E731
    assert sorted(map(key, again)) == sorted(map(key, original))
