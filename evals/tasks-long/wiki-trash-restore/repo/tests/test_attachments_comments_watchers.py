import pytest
from conftest import kitchen
from leafwiki import AttachmentNotFound, CommentNotFound
from leafwiki.errors import AttachmentTooLarge


def test_attachments_round_trip(wiki) -> None:
    kitchen(wiki)
    attachment = wiki.attach("Kettle", "manual.pdf", b"%PDF-1.4 kettle", "bo")
    assert attachment.content_type == "application/pdf"
    assert attachment.size == 15
    assert wiki.attachment("Kettle", "manual.pdf") == b"%PDF-1.4 kettle"
    assert [a.name for a in wiki.attachments("Kettle")] == ["manual.pdf"]
    wiki.detach("Kettle", "manual.pdf")
    with pytest.raises(AttachmentNotFound):
        wiki.attachment("Kettle", "manual.pdf")


def test_attachments_have_a_size_limit(wiki) -> None:
    kitchen(wiki)
    wiki.set_setting("max_attachment_bytes", 10)
    with pytest.raises(AttachmentTooLarge):
        wiki.attach("Kettle", "big.bin", b"x" * 11)


def test_the_same_content_is_stored_once(wiki) -> None:
    kitchen(wiki)
    wiki.attach("Kettle", "a.txt", b"same")
    wiki.attach("Teapot", "b.txt", b"same")
    assert len(wiki.store.blob_keys()) == 1


def test_comments_and_replies(wiki) -> None:
    kitchen(wiki)
    first = wiki.comment("Kettle", "Which vinegar?", "cy")
    reply = wiki.comment("Kettle", "White, diluted.", "bo", reply_to=first.id)
    assert [c.text for c in wiki.comments("Kettle")] == ["Which vinegar?", "White, diluted."]
    (thread,) = wiki.comment_threads("Kettle")
    assert thread.replies[0].comment.id == reply.id
    wiki.edit_comment(reply.id, "White vinegar, half and half.")
    assert wiki.comments("Kettle")[1].edited_at is not None
    assert wiki.delete_comment(first.id) == 2
    assert wiki.comments("Kettle") == []
    with pytest.raises(CommentNotFound):
        wiki.edit_comment(first.id, "gone")


def test_recent_comments_span_the_wiki(wiki) -> None:
    kitchen(wiki)
    wiki.comment("Kettle", "one", "cy")
    wiki.comment("Teapot", "two", "ana")
    assert [(t, c.text) for t, c in wiki.recent_comments()] == [("Teapot", "two"), ("Kettle", "one")]


def test_watchers_are_told_what_happened(wiki) -> None:
    kitchen(wiki)
    wiki.watch("Kettle", "cy")
    wiki.watch("Kettle", "dee")
    wiki.edit_page("Kettle", "Use citric acid.", "cy")
    wiki.comment("Kettle", "Thanks!", "dee")
    wiki.attach("Kettle", "photo.png", b"\x89PNG", "ana")
    wiki.rename_page("Kettle", "Jug", "ana")
    events = [(m.to, m.event, m.page, m.by) for m in wiki.outbox()]
    assert events == [
        ("dee", "edited", "Kettle", "cy"),
        ("cy", "commented", "Kettle", "dee"),
        ("cy", "attached", "Kettle", "ana"),
        ("dee", "attached", "Kettle", "ana"),
        ("cy", "renamed", "Jug", "ana"),
        ("dee", "renamed", "Jug", "ana"),
    ]
    assert wiki.watched_by("cy") == ["Jug"]
    assert len(wiki.drain_outbox()) == 6
    assert wiki.outbox() == []


def test_deleting_tells_watchers_and_forgets_them(wiki) -> None:
    kitchen(wiki)
    wiki.watch("Kettle", "cy")
    wiki.delete_page("Kettle", "ana")
    assert [(m.to, m.event, m.page) for m in wiki.outbox()] == [("cy", "deleted", "Kettle")]
    assert wiki.watched_by("cy") == []
