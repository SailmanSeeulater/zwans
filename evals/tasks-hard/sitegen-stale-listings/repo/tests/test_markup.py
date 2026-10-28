from sitegen.markup import first_paragraph, inline, plain_text, render


def test_paragraphs_and_headings() -> None:
    html = render("# Title\n\nOne line\nand another.\n\nSecond.")
    assert html == "<h1>Title</h1>\n<p>One line and another.</p>\n<p>Second.</p>"


def test_inline_markup() -> None:
    assert inline("a *b* **c** `d*e*` [f](https://x.org)") == (
        'a <em>b</em> <strong>c</strong> <code>d*e*</code> <a href="https://x.org">f</a>'
    )


def test_raw_html_is_escaped() -> None:
    assert render("<script>alert(1)</script>") == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"


def test_lists_quotes_and_code() -> None:
    text = "- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n```python\nx = 1 < 2\n```"
    assert render(text) == (
        "<ul><li>one</li><li>two</li></ul>\n"
        "<ol><li>first</li><li>second</li></ol>\n"
        "<blockquote><p>quoted</p></blockquote>\n"
        '<pre><code class="language-python">x = 1 &lt; 2</code></pre>'
    )


def test_first_paragraph_skips_headings_and_code() -> None:
    assert (
        first_paragraph("## Intro\n\n```\ncode\n```\n\nThe real\nstart.\n\nMore.")
        == "The real start."
    )
    assert first_paragraph("# Only a heading") == ""


def test_plain_text() -> None:
    assert plain_text("Some *very* `nice` [text](/x).") == "Some very nice text."
