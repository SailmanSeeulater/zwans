import json

from conftest import DATA, ids


def saved_tags(cli) -> dict[int, list[str]]:
    bookmarks = json.loads(cli.path.read_text("utf-8"))["bookmarks"]
    for b in bookmarks:
        assert len(set(b["tags"])) == len(b["tags"]), b
        assert "folder" not in b
    return {b["id"]: sorted(b["tags"]) for b in bookmarks}


def test_add_list_and_find(cli) -> None:
    assert cli(
        "add",
        "https://docs.python.org/3/",
        "--title",
        "Python docs",
        "--tag",
        "dev",
        "--tag",
        "python",
    ) == (
        0,
        "added 1\n",
        "",
    )
    cli("add", "https://www.gutenberg.org/", "--title", "Gutenberg", "--star")
    cli(
        "add",
        "https://docs.pytest.org/",
        "--title",
        "pytest",
        "--tag",
        "python",
        "--tag",
        "testing",
    )

    assert ids(cli("list")[1]) == [1, 2, 3]
    assert ids(cli("list", "--starred")[1]) == [2]
    assert ids(cli("list", "--tag", "python")[1]) == [1, 3]
    assert ids(cli("list", "--tag", "testing")[1]) == [3]
    assert ids(cli("list", "--tag", "nothing")[1]) == []
    assert ids(cli("find", "testing")[1]) == [3]
    assert cli("list")[1].splitlines()[1] == "   2 * Gutenberg  <https://www.gutenberg.org/>"

    doc = json.loads(cli.path.read_text("utf-8"))
    assert doc["version"] == 4
    assert doc["bookmarks"][0]["added"] == "2026-03-01"


def test_tags_are_normalised(cli) -> None:
    cli(
        "add",
        "https://scikit-learn.org/",
        "--tag",
        "Machine Learning",
        "--tag",
        "ML",
        "--tag",
        "machine learning",
    )
    assert saved_tags(cli) == {1: ["machine-learning", "ml"]}
    assert ids(cli("list", "--tag", "machine-learning")[1]) == [1]


def test_find_looks_at_tags(cli) -> None:
    cli("add", "https://example.com/snakes", "--title", "Snake facts", "--tag", "python")
    cli("add", "https://example.com/other", "--title", "Other", "--tag", "misc")
    assert ids(cli("find", "pyth")[1]) == [1]
    assert ids(cli("find", "MISC")[1]) == [2]


def test_tagging_and_untagging(cli) -> None:
    cli("add", "https://docs.python.org/3/", "--tag", "dev")
    cli("add", "https://www.gutenberg.org/")
    assert cli("tag", "1", "Reference", "python", "dev")[0] == 0
    assert cli("tag", "2", "reading")[0] == 0
    assert saved_tags(cli) == {1: ["dev", "python", "reference"], 2: ["reading"]}
    assert cli("untag", "1", "dev", "python")[0] == 0
    assert saved_tags(cli) == {1: ["reference"], 2: ["reading"]}
    assert cli("tag", "9", "x")[0] == 1


def test_the_tags_command_counts_bookmarks_per_tag(cli) -> None:
    cli("add", "https://docs.python.org/3/", "--tag", "python", "--tag", "dev")
    cli("add", "https://docs.pytest.org/", "--tag", "python", "--tag", "testing")
    cli("add", "https://www.gutenberg.org/")
    assert cli("tags")[1] == "dev  1\npython  2\ntesting  1\n"


def test_changing_bookmarks(cli) -> None:
    cli("add", "https://docs.python.org/3/")
    cli("add", "https://www.gutenberg.org/")
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
    assert ids(cli("list", "--tag", "machine-learning")[1]) == [3]
    assert ids(cli("list", "--tag", "dev")[1]) == [2, 3]


def test_old_files_work_with_tags_straight_away(cli, old_file) -> None:
    cli.path = old_file(1)
    assert ids(cli("list", "--tag", "python")[1]) == [1, 4]
    assert ids(cli("list", "--tag", "long-reads")[1]) == [2]
    assert ids(cli("find", "long-r")[1]) == [2]
    assert cli("tags")[1].splitlines()[0] == "dev  2"
    assert json.loads(cli.path.read_text("utf-8"))["version"] == 1  # reading never rewrites

    cli("tag", "3", "news")
    assert saved_tags(cli) == {
        1: ["dev", "python"],
        2: ["long-reads", "reading"],
        3: ["news"],
        4: ["dev", "python", "testing"],
    }
    assert (cli.path.parent / f"{cli.path.name}.v1.bak").exists()


def test_check_and_upgrade_an_old_file(cli, old_file) -> None:
    cli.path = old_file(3)
    assert cli("check")[1].startswith("ok: 3 bookmarks")
    assert json.loads(cli.path.read_text("utf-8"))["version"] == 3

    code, out, _ = cli("upgrade")
    assert code == 0
    assert out.startswith("upgraded from format 3 to 4")
    assert (cli.path.parent / f"{cli.path.name}.v3.bak").exists()
    assert saved_tags(cli) == {
        2: ["dev", "python", "web-frameworks"],
        5: ["cooking", "home"],
        6: [],
    }
    assert cli("upgrade")[1].startswith("already at format 4")


def test_a_hand_edited_file_with_bad_tags_is_refused(cli) -> None:
    cli("add", "https://docs.python.org/3/", "--tag", "dev")
    doc = json.loads(cli.path.read_text("utf-8"))
    doc["bookmarks"][0]["tags"] = ["Dev"]
    cli.path.write_text(json.dumps(doc), "utf-8")
    assert cli("check")[0] == 1


def test_a_file_from_the_future_is_refused(cli) -> None:
    cli.path.write_text('{"version": 999, "bookmarks": []}', "utf-8")
    code, _, err = cli("list")
    assert code == 1
    assert "newer" in err
