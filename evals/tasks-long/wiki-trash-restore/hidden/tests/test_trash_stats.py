from conftest import stocked
from leafwiki.stats import page_stats, wiki_stats


def test_stats_leave_out_the_trash(any_wiki) -> None:
    wiki = any_wiki
    stocked(wiki)
    wiki.comment("Teapot", "Lovely pot.", "fay")
    before = wiki_stats(wiki)
    assert before["pages"] == 3
    assert before["comments"] == 3
    assert before["trashed"] == 0

    entry = wiki.delete_page("Kettle", "ana")
    stats = wiki_stats(wiki)
    assert stats["pages"] == 2
    assert stats["revisions"] == 2
    assert stats["attachments"] == 0
    assert stats["attachment_bytes"] == 0
    assert stats["comments"] == 1
    assert stats["tags"] == 2
    assert stats["authors"] == 2  # ana and cy; bo and eve only wrote the Kettle
    assert stats["top_linked"] == [["Teapot", 1]]
    assert stats["orphans"] == ["Front Page"]
    assert stats["wanted"] == ["Kettle", "Toaster"]
    assert stats["words"] == before["words"] - 12
    assert stats["trashed"] == 1

    wiki.restore_page(entry)
    assert wiki_stats(wiki) == before


def test_trashed_counts_entries(wiki) -> None:
    stocked(wiki)
    first = wiki.delete_page("Kettle")
    wiki.delete_page("Teapot")
    assert wiki_stats(wiki)["trashed"] == 2
    wiki.purge_page(first)
    assert wiki_stats(wiki)["trashed"] == 1
    assert wiki_stats(wiki)["pages"] == 1


def test_page_stats_count_only_live_backlinks(wiki) -> None:
    stocked(wiki)
    entry = wiki.delete_page("Teapot")
    assert page_stats(wiki, "Kettle")["backlinks"] == 1
    wiki.restore_page(entry)
    assert page_stats(wiki, "Kettle")["backlinks"] == 2
    assert page_stats(wiki, "Kettle")["comments"] == 2
