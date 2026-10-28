from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from sitegen.filters import Markup
from sitegen.templates import Engine, TemplateError


@dataclass
class Settings:
    date_format: str = "%d %b %Y"
    base_url: str = "https://example.org/"


def render(source: str, **values: object) -> str:
    return Engine(None, {"t.html": source}, Settings()).render("t.html", values)


def test_values_are_escaped_unless_safe() -> None:
    assert render("{{ a }} {{ a|safe }}", a="<b>") == "&lt;b&gt; <b>"
    assert render("{{ m }}", m=Markup("<i>x</i>")) == "<i>x</i>"


def test_attribute_and_key_lookup() -> None:
    @dataclass
    class Post:
        title: str

    assert render("{{ p.title }}/{{ d.k }}/{{ missing.x }}", p=Post("T"), d={"k": 1}) == "T/1/"


def test_filters() -> None:
    assert render("{{ d|date }}|{{ d|date:'%Y' }}", d=date(2026, 3, 4)) == "04 Mar 2026|2026"
    assert render("{{ n|plural:'post' }}, {{ m|plural:'post' }}", n=1, m=3) == "1 post, 3 posts"
    assert render("{{ 'a/b/'|absolute }} {{ 'a/'|url }}") == "https://example.org/a/b/ /a/"
    assert render("{{ xs|join:' + ' }}", xs=[1, 2]) == "1 + 2"


def test_if_elif_else() -> None:
    source = "{% if a %}A{% elif b %}B{% else %}C{% endif %}"
    assert [render(source, a=1, b=1), render(source, a=0, b=1), render(source, a=0, b=0)] == [
        "A",
        "B",
        "C",
    ]
    assert render("{% if not a %}no{% endif %}", a=[]) == "no"


def test_for_loops() -> None:
    source = "{% for x in xs %}{{ loop.index }}={{ x }}{% if not loop.last %},{% endif %}{% else %}none{% endfor %}"
    assert render(source, xs=["a", "b"]) == "1=a,2=b"
    assert render(source, xs=[]) == "none"


def test_include_and_override(tmp_path: Path) -> None:
    (tmp_path / "inner.html").write_text("[{{ x }}]", encoding="utf-8")
    engine = Engine(
        tmp_path, {"outer.html": "<{% include 'inner.html' %}>", "inner.html": "?"}, Settings()
    )
    assert engine.render("outer.html", {"x": 1}) == "<[1]>"


def test_fingerprint_follows_template_changes(tmp_path: Path) -> None:
    engine = Engine(tmp_path, {"a.html": "A"}, Settings())
    before = engine.fingerprint()
    (tmp_path / "a.html").write_text("changed", encoding="utf-8")
    assert engine.fingerprint() != before
    assert engine.render("a.html", {}) == "changed"


def test_errors() -> None:
    with pytest.raises(TemplateError, match="missing"):
        render("{% if a %}x")
    with pytest.raises(TemplateError, match="unknown filter"):
        render("{{ a|nope }}", a=1)
