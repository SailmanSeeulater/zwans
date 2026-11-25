"""Block structure of leafwiki markup.

The markup is a small Markdown-like language:

* ``# Title``, ``## Section``, ``### Subsection`` headings
* paragraphs separated by blank lines
* ``- item`` or ``* item`` bullet lists, ``1. item`` numbered lists
* ``> quoted`` lines
* fenced code blocks between lines of three backticks
* ``----`` on its own line for a rule

Inline markup (links, emphasis, code) is handled by :mod:`leafwiki.markup.inline`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_RULE = re.compile(r"^\s*-{4,}\s*$")
_FENCE = re.compile(r"^```\s*([\w+-]*)\s*$")


@dataclass
class Block:
    kind: str  # heading, paragraph, bullets, numbers, quote, code, rule
    text: str = ""
    level: int = 0
    items: list[str] = field(default_factory=list)
    language: str = ""


def parse_blocks(source: str) -> list[Block]:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []
    i = 0

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", " ".join(s.strip() for s in paragraph)))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            flush()
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence, or the end of the text
            blocks.append(Block("code", "\n".join(body), language=fence.group(1)))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", heading.group(2), level=len(heading.group(1))))
            i += 1
            continue
        if _RULE.match(line):
            flush()
            blocks.append(Block("rule"))
            i += 1
            continue
        for kind, pattern in (("bullets", _BULLET), ("numbers", _NUMBERED)):
            if pattern.match(line):
                flush()
                items: list[str] = []
                while i < len(lines):
                    match = pattern.match(lines[i])
                    if match:
                        items.append(match.group(1).strip())
                    elif lines[i].startswith(("  ", "\t")) and items and lines[i].strip():
                        items[-1] += " " + lines[i].strip()
                    else:
                        break
                    i += 1
                blocks.append(Block(kind, items=items))
                break
        else:
            quote = _QUOTE.match(line)
            if quote:
                flush()
                quoted: list[str] = []
                while i < len(lines):
                    match = _QUOTE.match(lines[i])
                    if not match:
                        break
                    quoted.append(match.group(1))
                    i += 1
                blocks.append(Block("quote", " ".join(q.strip() for q in quoted if q.strip())))
                continue
            paragraph.append(line)
            i += 1
            continue
    flush()
    return blocks


def inline_texts(blocks: list[Block]) -> list[str]:
    """Every piece of text that inline markup applies to (code blocks excluded)."""
    texts: list[str] = []
    for block in blocks:
        if block.kind in ("heading", "paragraph", "quote"):
            texts.append(block.text)
        elif block.kind in ("bullets", "numbers"):
            texts.extend(block.items)
    return texts
