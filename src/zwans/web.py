"""Web search and web fetch: tools the Claude API runs itself, on Anthropic's servers.

Zwans only declares them. The model's calls and their results come back inside its reply,
as server_tool_use and web_*_tool_result blocks, and go back to the API unchanged. The loop
reads them only to show what happened and to note that web content is now in the
conversation.

Because the API runs them, the permission policy can't stop a single search or fetch, and
neither the jail nor Docker keeps them off the network. Turn them off with `web = false`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from zwans.messages import ContentBlock, RawBlock

SEARCH = "web_search"
FETCH = "web_fetch"
NAMES = frozenset({SEARCH, FETCH})
RESULT_TYPES = frozenset({"web_search_tool_result", "web_fetch_tool_result"})
SEARCH_DOLLARS = 0.01  # $10 per 1,000 searches, on top of tokens; fetches cost only tokens
FETCH_MAX_TOKENS = 25_000  # a page longer than this is cut, so one fetch can't fill the context

# Newer models filter results with code before reading them, which saves tokens. The
# versions without the filter are for the rest.
FILTERING = ("web_search_20260209", "web_fetch_20260209")
BASIC = ("web_search_20250305", "web_fetch_20250910")


def tool_params(filtering: bool) -> list[dict[str, Any]]:
    search, fetch = FILTERING if filtering else BASIC
    return [
        {"type": search, "name": SEARCH},
        {"type": fetch, "name": FETCH, "max_content_tokens": FETCH_MAX_TOKENS},
    ]


@dataclass(frozen=True)
class WebCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class WebResult:
    call_id: str
    content: str  # a short account for people: titles and addresses, not the pages
    is_error: bool


def web_calls(blocks: Iterable[ContentBlock]) -> list[WebCall]:
    calls = []
    for block in blocks:
        if isinstance(block, RawBlock) and block.type == "server_tool_use":
            name = block.data.get("name")
            if name in NAMES:
                args = dict(block.data.get("input") or {})
                calls.append(WebCall(str(block.data.get("id")), str(name), args))
    return calls


def web_results(blocks: Iterable[ContentBlock]) -> list[WebResult]:
    results = []
    for block in blocks:
        if isinstance(block, RawBlock) and block.type in RESULT_TYPES:
            content, is_error = describe(block.data.get("content"))
            results.append(WebResult(str(block.data.get("tool_use_id")), content, is_error))
    return results


def describe(content: Any) -> tuple[str, bool]:
    """What a result block holds, in a few lines. An error is an object with an error_code;
    search results are a list; a fetched page is one object holding a document."""
    if isinstance(content, list):
        lines = [f"{r.get('title') or '(untitled)'}\n  {r.get('url', '')}" for r in content]
        return ("\n".join(lines) or "No results."), False
    if not isinstance(content, dict):
        return "No result.", True
    if "error_code" in content:
        return f"The API couldn't do this: {content['error_code']}", True
    document = content.get("content") or {}
    source = document.get("source") or {}
    title = document.get("title") or content.get("url", "")
    size = len(source.get("data") or "") if source.get("type") == "text" else 0
    what = f"{size:,} characters" if size else str(source.get("media_type", "a document"))
    return f"{title}\n  {content.get('url', '')}\n  {what}", False
