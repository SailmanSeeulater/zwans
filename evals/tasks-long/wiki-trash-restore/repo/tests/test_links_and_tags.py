from conftest import kitchen
from leafwiki.markup import extract_links, plain_text, render_html


def test_links_are_found_outside_code() -> None:
    text = "See [[Kettle]], [[kettle|again]] and [[Tea Pot|the pot]].\n\n```\n[[Not A Link]]\n```\n`[[nor this]]`"
    assert [(l.target, l.slug) for l in extract_links(text)] == [
        ("Kettle", "kettle"),
        ("Tea Pot", "tea-pot"),
    ]


def test_rendering_marks_missing_pages() -> None:
    html = render_html("[[Kettle]] and [[Toaster|toast]]", exists=lambda slug: slug == "kettle")
    assert '<a class="wikilink" href="/pages/kettle">Kettle</a>' in html
    assert '<a class="wikilink missing" href="/pages/toaster">toast</a>' in html


def test_plain_text_drops_markup() -> None:
    assert plain_text("# Title\n\n**Bold** and [[Kettle|a kettle]]\n\n- one\n- two") == (
        "Title\nBold and a kettle\none\ntwo"
    )


def test_backlinks(wiki) -> None:
    kitchen(wiki)
    assert wiki.backlinks("Kettle") == ["Front Page", "Teapot"]
    assert wiki.backlinks("Front Page") == ["Kettle"]
    assert wiki.backlinks("Toaster") == ["Front Page"]
    wiki.edit_page("Teapot", "No links any more.")
    assert wiki.backlinks("Kettle") == ["Front Page"]


def test_the_page_renders_with_its_links_checked(wiki) -> None:
    kitchen(wiki)
    html = wiki.render("Front Page")
    assert 'class="wikilink" href="/pages/kettle"' in html
    assert 'class="wikilink missing" href="/pages/toaster"' in html
    wiki.create_page("Toaster", "Crumbs everywhere.")
    assert 'class="wikilink" href="/pages/toaster"' in wiki.render("Front Page")


def test_wanted_and_orphan_pages(wiki) -> None:
    kitchen(wiki)
    assert wiki.wanted() == {"toaster": ["Front Page"]}
    wiki.create_page("Lonely", "Nobody links here.")
    assert wiki.orphans() == ["Lonely"]


def test_links_listing(wiki) -> None:
    kitchen(wiki)
    assert [(l.target, l.exists) for l in wiki.links("Front Page")] == [
        ("Kettle", True),
        ("Teapot", True),
        ("Toaster", False),
    ]


def test_tags_are_counted(wiki) -> None:
    kitchen(wiki)
    assert wiki.tags() == {"appliances": 1, "home": 1, "kitchen": 2}
    assert wiki.pages_tagged("kitchen") == ["Kettle", "Teapot"]
    wiki.set_tags("Teapot", ["Tea Time", "#kitchen"], "cy")
    assert wiki.page("Teapot").tags == ["kitchen", "tea-time"]
    wiki.remove_tags("Kettle", ["kitchen"])
    assert wiki.tags() == {"appliances": 1, "home": 1, "kitchen": 1, "tea-time": 1}


def test_deleting_a_page_drops_its_tags_and_links(wiki) -> None:
    kitchen(wiki)
    wiki.delete_page("Teapot")
    assert wiki.tags() == {"appliances": 1, "home": 1, "kitchen": 1}
    assert wiki.backlinks("Kettle") == ["Front Page"]
