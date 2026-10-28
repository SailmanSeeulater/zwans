"""A Markdown subset: headings, paragraphs, lists, quotes, fenced code, and inline
emphasis, code and links. Raw HTML is escaped, never passed through."""

import html
import re
from functools import lru_cache

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^```\s*([\w+-]*)\s*$")
_RULE = re.compile(r"^(\*\s*){3,}$|^(-\s*){3,}$")

_CODE_SPAN = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_STRONG = re.compile(r"\*\*(.+?)\*\*")
_EM = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")


def inline(text: str) -> str:
    """Render inline markup in one block of text."""
    # Code spans are cut out first so nothing inside them is touched.
    spans: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        spans.append(f"<code>{html.escape(match.group(1), quote=False)}</code>")
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN.sub(keep_code, text)
    text = html.escape(text, quote=False)
    text = _LINK.sub(lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', text)
    text = _STRONG.sub(r"<strong>\1</strong>", text)
    text = _EM.sub(r"<em>\1</em>", text)
    return re.sub("\x00(\\d+)\x00", lambda m: spans[int(m.group(1))], text)


def blocks(text: str) -> list[tuple[str, list[str]]]:
    """Split text into (kind, lines) blocks: heading, para, ul, ol, quote, code, rule."""
    result: list[tuple[str, list[str]]] = []
    lines = text.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        fence = _FENCE.match(stripped)
        if fence:
            body: list[str] = [fence.group(1)]
            index += 1
            while index < len(lines) and lines[index].strip() != "```":
                body.append(lines[index])
                index += 1
            result.append(("code", body))
            index += 1  # the closing fence (or the end of the text)
            continue
        if _HEADING.match(stripped):
            result.append(("heading", [stripped]))
            index += 1
            continue
        if _RULE.match(stripped):
            result.append(("rule", []))
            index += 1
            continue
        for kind, pattern in (("ul", _BULLET), ("ol", _NUMBERED)):
            if pattern.match(stripped):
                items: list[str] = []
                while index < len(lines) and lines[index].strip():
                    item = pattern.match(lines[index].strip())
                    if item:
                        items.append(item.group(1))
                    elif items:
                        items[-1] += " " + lines[index].strip()  # a continuation line
                    index += 1
                result.append((kind, items))
                break
        else:
            if stripped.startswith(">"):
                quoted: list[str] = []
                while index < len(lines) and lines[index].strip().startswith(">"):
                    quoted.append(lines[index].strip()[1:].strip())
                    index += 1
                result.append(("quote", quoted))
                continue
            para: list[str] = []
            while index < len(lines):
                current = lines[index].strip()
                if not current or _FENCE.match(current) or _HEADING.match(current):
                    break
                if para and (current.startswith(">") or _BULLET.match(current)):
                    break
                para.append(current)
                index += 1
            result.append(("para", para))
    return result


def _render_block(kind: str, lines: list[str]) -> str:
    if kind == "heading":
        match = _HEADING.match(lines[0])
        assert match
        level = len(match.group(1))
        return f"<h{level}>{inline(match.group(2))}</h{level}>"
    if kind == "code":
        language, body = lines[0], lines[1:]
        attribute = f' class="language-{language}"' if language else ""
        code = html.escape("\n".join(body), quote=False)
        return f"<pre><code{attribute}>{code}</code></pre>"
    if kind == "rule":
        return "<hr>"
    if kind in ("ul", "ol"):
        items = "".join(f"<li>{inline(item)}</li>" for item in lines)
        return f"<{kind}>{items}</{kind}>"
    if kind == "quote":
        inner = render("\n".join(lines))
        return f"<blockquote>{inner}</blockquote>"
    return f"<p>{inline(' '.join(lines))}</p>"


@lru_cache(maxsize=1024)
def render(text: str) -> str:
    """Render a whole document to HTML."""
    return "\n".join(_render_block(kind, lines) for kind, lines in blocks(text))


def first_paragraph(text: str) -> str:
    """The text of the first paragraph block, or "" if there is none."""
    for kind, lines in blocks(text):
        if kind == "para":
            return " ".join(lines)
    return ""


def plain_text(text: str) -> str:
    """Rendered text without any tags, for word counts and feeds."""
    return re.sub(r"<[^>]+>", "", html.unescape(render(text)))
