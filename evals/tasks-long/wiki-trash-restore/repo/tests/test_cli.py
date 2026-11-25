import json


def test_create_show_and_list(cli, tmp_path) -> None:
    assert cli("new", "Kettle", "--text", "Boil it.", "--tag", "kitchen")[0] == 0
    code, out, _ = cli("show", "kettle")
    assert code == 0
    assert out.splitlines()[:2] == ["# Kettle", "tags: kitchen"]
    assert "Boil it." in out
    assert cli("list")[1] == "Kettle\n"
    assert cli("list", "--tag", "kitchen")[1] == "Kettle\n"


def test_edit_history_and_revert(cli) -> None:
    cli("new", "Kettle", "--text", "one")
    assert cli("edit", "Kettle", "--text", "two", "--summary", "better")[1] == (
        "Kettle is now at revision 2\n"
    )
    out = cli("history", "Kettle")[1]
    assert "better" in out.splitlines()[0]
    cli("revert", "Kettle", "1")
    assert "one" in cli("show", "Kettle")[1]


def test_unknown_pages_fail_cleanly(cli) -> None:
    code, out, err = cli("show", "Nope")
    assert code == 1
    assert "no page called 'Nope'" in err


def test_delete_and_rename(cli) -> None:
    cli("new", "Kettle", "--text", "one")
    assert cli("rename", "Kettle", "Jug")[1] == "renamed to Jug\n"
    assert cli("delete", "jug")[1] == "deleted Jug\n"
    assert cli("list")[1] == ""


def test_search_tags_links(cli) -> None:
    cli("new", "Kettle", "--text", "Descale with vinegar. [[Teapot]]", "--tag", "kitchen")
    cli("new", "Teapot", "--text", "Warm it.", "--tag", "kitchen")
    assert cli("search", "vinegar")[1].splitlines()[0] == "Kettle"
    assert cli("search", "giraffe")[1] == "no matches\n"
    assert cli("tags")[1] == "kitchen (2)\n"
    cli("tag", "Teapot", "+tea", "-kitchen")
    assert cli("tags")[1] == "kitchen (1)\ntea (1)\n"
    out = cli("links", "Teapot")[1]
    assert out.endswith("linked from:\n  Kettle\n")


def test_attach_comment_watch(cli, tmp_path) -> None:
    cli("new", "Kettle", "--text", "x")
    (tmp_path / "manual.txt").write_text("manual")
    assert cli("attach", "Kettle", str(tmp_path / "manual.txt"))[1] == "attached manual.txt (6 bytes)\n"
    assert cli("comment", "Kettle", "hello")[1] == "added c1\n"
    cli("--as", "cy", "watch", "Kettle")
    assert cli("--as", "cy", "watching")[1] == "Kettle\n"
    cli("edit", "Kettle", "--text", "y")
    (line,) = cli("outbox", "--drain")[1].splitlines()
    assert json.loads(line) == {
        "to": "cy",
        "event": "edited",
        "page": "Kettle",
        "by": "ana",
        "at": "2026-03-01T09:00:00Z",
    }
    assert cli("outbox")[1] == ""


def test_reports(cli, tmp_path) -> None:
    cli("new", "Kettle", "--text", "x [[Teapot]]")
    stats = json.loads(cli("stats", "--json")[1])
    assert stats["pages"] == 1
    assert stats["wanted"] == ["Teapot"]
    assert "<rss" in cli("feed")[1]
    assert "kettle.html" in cli("sitemap")[1]
    assert cli("changes")[1].startswith("2026-03-01 09:00 create Kettle by ana")
    assert cli("export", str(tmp_path / "site"))[0] == 0
    assert (tmp_path / "site" / "pages" / "kettle.html").exists()


def test_config_maintain_backup(cli, tmp_path) -> None:
    assert cli("config", "keep_revisions", "2")[1] == "keep_revisions = 2\n"
    assert cli("config", "nope", "1")[0] == 2
    assert "keep_revisions = 2" in cli("config")[1]
    assert cli("maintain")[0] == 0
    cli("new", "Kettle", "--text", "x")
    assert cli("check")[1] == "no problems found\n"
    assert cli("backup", str(tmp_path / "b.zip"))[0] == 0
    code, out, _ = cli("unpack-backup", str(tmp_path / "b.zip"), str(tmp_path / "copy"))
    assert (code, out) == (0, f"restored 1 page into {tmp_path / 'copy'}\n")
