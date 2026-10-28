import json

from conftest import DATA, ids


def test_add_list_and_find(cli) -> None:
    assert cli(
        "add", "https://docs.python.org/3/", "--title", "Python docs", "--folder", "Dev/Python"
    ) == (
        0,
        "added 1\n",
        "",
    )
    cli("add", "https://www.gutenberg.org/", "--title", "Gutenberg", "--star")
    cli("add", "https://docs.pytest.org/", "--title", "pytest", "--folder", "Dev/Python/Testing")

    assert ids(cli("list")[1]) == [1, 2, 3]
    assert ids(cli("list", "--starred")[1]) == [2]
    assert ids(cli("list", "--folder", "Dev/Python")[1]) == [1, 3]
    assert ids(cli("find", "testing")[1]) == [3]
    assert cli("list")[1].splitlines()[1] == "   2 * Gutenberg  <https://www.gutenberg.org/>"

    doc = json.loads(cli.path.read_text("utf-8"))
    assert doc["bookmarks"][0]["added"] == "2026-03-01"


def test_changing_bookmarks(cli) -> None:
    cli("add", "https://docs.python.org/3/", "--folder", "Dev")
    cli("add", "https://www.gutenberg.org/")
    assert cli("move", "1", "Reference")[0] == 0
    assert cli("folders")[1] == "Reference  1\n"
    assert cli("visit", "2") == (0, "https://www.gutenberg.org/\n", "")
    cli("star", "2")
    cli("rm", "1")
    doc = json.loads(cli.path.read_text("utf-8"))
    assert [(b["id"], b["visits"], b["starred"]) for b in doc["bookmarks"]] == [(2, 1, True)]


def test_errors_exit_with_1(cli) -> None:
    cli("add", "https://docs.python.org/3/")
    code, _, err = cli("add", "https://docs.python.org/3")
    assert (code, err.startswith("error: ")) == (1, True)
    assert cli("rm", "9")[0] == 1
    assert cli("add", "not a url")[0] == 1


def test_import_and_export(cli) -> None:
    assert cli("import", str(DATA / "firefox.html")) == (0, "imported 4, skipped 1\n", "")
    code, out, _ = cli("export")
    assert code == 0
    assert out.count("<DT><A ") == 4


def test_check_and_upgrade_an_old_file(cli, old_file) -> None:
    cli.path = old_file(1)
    assert cli("check")[1].startswith("ok: 4 bookmarks")
    assert json.loads(cli.path.read_text("utf-8"))["version"] == 1  # reading never rewrites

    code, out, _ = cli("upgrade")
    assert code == 0
    assert out.startswith("upgraded from format 1 to ")
    assert (cli.path.parent / f"{cli.path.name}.v1.bak").exists()
    assert cli("upgrade")[1].startswith("already at format ")


def test_a_file_from_the_future_is_refused(cli) -> None:
    cli.path.write_text('{"version": 999, "bookmarks": []}', "utf-8")
    code, _, err = cli("list")
    assert code == 1
    assert "newer" in err
