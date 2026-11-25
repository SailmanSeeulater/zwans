import json


def trash_lines(cli) -> list[list[str]]:
    code, out, _ = cli("trash")
    assert code == 0
    return [line.split("  ") for line in out.splitlines() if line.strip()]


def test_delete_trash_restore(cli) -> None:
    cli("new", "Kettle", "--text", "Descale with vinegar.", "--tag", "kitchen")
    cli("--as", "cy", "watch", "Kettle")
    assert cli("delete", "kettle")[1] == "deleted Kettle\n"
    (row,) = trash_lines(cli)
    assert row[1:] == ["Kettle", "2026-03-01T09:00:00Z", "ana"]
    assert cli("show", "Kettle")[0] == 1
    assert cli("search", "vinegar")[1] == "no matches\n"
    assert cli("list")[1] == ""
    assert cli("restore", row[0])[1] == "restored Kettle\n"
    assert "Descale with vinegar." in cli("show", "Kettle")[1]
    assert cli("search", "vinegar")[1].splitlines()[0] == "Kettle"
    assert cli("tags")[1] == "kitchen (1)\n"
    assert cli("--as", "cy", "watching")[1] == "Kettle\n"
    assert trash_lines(cli) == []


def test_restore_under_a_new_title(cli) -> None:
    cli("new", "Kettle", "--text", "old")
    cli("delete", "Kettle")
    cli("new", "Kettle", "--text", "new")
    ((entry, *_),) = trash_lines(cli)
    code, _, err = cli("restore", entry)
    assert code == 1 and err
    assert cli("restore", entry, "--title", "Old Kettle")[1] == "restored Old Kettle\n"
    assert cli("list")[1] == "Kettle\nOld Kettle\n"


def test_purge_and_unknown_entries(cli, monkeypatch) -> None:
    cli("new", "Kettle", "--text", "x")
    cli("new", "Teapot", "--text", "y")
    cli("delete", "Kettle")
    monkeypatch.setenv("LEAFWIKI_NOW", "2026-03-01T10:00:00Z")
    cli("--as", "bo", "delete", "Teapot")
    rows = trash_lines(cli)
    assert [(r[1], r[3]) for r in rows] == [("Teapot", "bo"), ("Kettle", "ana")]
    kettle = rows[1][0]
    assert cli("purge", kettle)[1] == "purged Kettle\n"
    assert [r[1] for r in trash_lines(cli)] == ["Teapot"]
    for command in ("restore", "purge"):
        code, _, err = cli(command, kettle)
        assert code == 1 and err


def test_retention_from_the_command_line(cli, monkeypatch) -> None:
    assert cli("config", "trash_retention_days", "5")[1] == "trash_retention_days = 5\n"
    cli("new", "Kettle", "--text", "x")
    cli("delete", "Kettle")
    monkeypatch.setenv("LEAFWIKI_NOW", "2026-03-04T09:00:00Z")
    out = cli("maintain")[1]
    assert any("trash" in line and line.endswith(" 0") for line in out.splitlines())
    monkeypatch.setenv("LEAFWIKI_NOW", "2026-03-07T09:00:00Z")
    out = cli("maintain")[1]
    assert any("trash" in line and line.endswith(" 1") for line in out.splitlines())
    assert trash_lines(cli) == []


def test_stats_show_the_trash(cli) -> None:
    cli("new", "Kettle", "--text", "x [[Teapot]]")
    cli("new", "Teapot", "--text", "y")
    cli("delete", "Teapot")
    stats = json.loads(cli("stats", "--json")[1])
    assert stats["pages"] == 1
    assert stats["trashed"] == 1
    assert stats["wanted"] == ["Teapot"]
    assert cli("check")[1] == "no problems found\n"
