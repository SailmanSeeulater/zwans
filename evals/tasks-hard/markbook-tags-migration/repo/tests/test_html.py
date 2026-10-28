from conftest import DATA
from markbook.collection import Collection
from markbook.html_format import export_html, import_html, parse_html


def firefox() -> str:
    return (DATA / "firefox.html").read_text("utf-8")


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


def test_imported_folders() -> None:
    collection = Collection()
    import_html(collection, firefox())
    assert {b.title: b.folder for b in collection} == {
        "Wikipedia": "",
        "Python & friends": "Dev",
        "scikit-learn": "Dev/Machine Learning",
        "Serious Eats": "Recipes",
    }


def test_export_writes_a_browser_bookmark_file() -> None:
    collection = Collection()
    collection.add("https://docs.python.org/3/", "Python <docs>", "Dev/Python", added="2024-02-01")
    text = export_html(collection)
    assert text.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    assert (
        '<A HREF="https://docs.python.org/3/" ADD_DATE="1706745600">Python &lt;docs&gt;</A>' in text
    )


def test_export_then_import_gives_the_same_bookmarks() -> None:
    collection = Collection()
    collection.add("https://docs.python.org/3/", "Python docs", "Dev/Python", added="2024-02-01")
    collection.add("https://docs.pytest.org/", "pytest", "Dev/Python/Testing", added="2024-02-02")
    collection.add("https://www.gutenberg.org/", "Gutenberg", "", added="")
    collection.add(
        "https://www.seriouseats.com/", "Serious Eats", "Home/Cooking & Baking", added="2024-02-03"
    )

    again = Collection()
    import_html(again, export_html(collection))
    key = lambda b: (b.url, b.title, b.folder, b.added)  # noqa: E731
    assert sorted(map(key, again)) == sorted(map(key, collection))
