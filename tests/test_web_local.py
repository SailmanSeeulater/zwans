import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from zwans.config import Config, ConfigError, WebSearchConfig, load_config
from zwans.executor.local import LocalExecutor
from zwans.messages import Message
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Mode, Policy, PolicyFile
from zwans.providers.base import StreamItem
from zwans.providers.catalog import Resolved
from zwans.providers.fake import FakeProvider
from zwans.providers.router import ModelRouter
from zwans.runtime import open_session
from zwans.tools.base import Tool, ToolContext, ToolError, ToolOutput
from zwans.tools.web_local import (
    MAX_CHARS,
    WebFetchInput,
    WebFetchTool,
    WebSearchInput,
    WebSearchTool,
    to_text,
)

PAGE = """<!doctype html><html><head><title>  The   Docs </title>
<style>p { color: red }</style><script>alert("no")</script></head>
<body><nav><a href="/home">Home</a></nav>
<h1>Install</h1><p>Run <code>pip install zwans</code>, then read
<a href="guide.html">the guide</a>.</p>
<ul><li>One</li><li>Two &amp; three</li></ul>
<a href="https://example.org/x">https://example.org/x</a>
<a href="mailto:a@example.org">write</a></body></html>"""

Handler = Callable[[httpx.Request], httpx.Response]


async def public(host: str) -> list[str]:
    return ["93.184.216.34"]


def fetcher(handler: Handler, resolver: Any = public) -> WebFetchTool:
    return WebFetchTool(transport=httpx.MockTransport(handler), resolver=resolver)


def fetch(tool: WebFetchTool, ctx: ToolContext, url: str) -> ToolOutput:
    return asyncio.run(tool.run(WebFetchInput(url=url), ctx))


def html(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})


def permissions(
    tmp_path: Path, mode: Mode, *, allow: Sequence[str] = (), deny: Sequence[str] = ()
) -> Permissions:
    policy = Policy.default()
    policy.add(PolicyFile(mode=mode, allow=list(allow), deny=list(deny)), "test")
    executor = LocalExecutor(tmp_path)
    return Permissions(policy, lambda path: True, executor.relative, root=executor.root)


# -- a page as text


def test_a_page_becomes_text_with_its_headings_and_links() -> None:
    title, text = to_text(PAGE, "https://docs.example.com/install/")

    assert title == "The Docs"
    assert text.splitlines() == [
        "Home (https://docs.example.com/home)",
        "",
        "# Install",
        "",
        "Run pip install zwans, then read the guide (https://docs.example.com/install/guide.html).",
        "",
        "- One",
        "",
        "- Two & three",
        "",
        "https://example.org/x write",  # a link that is its own address isn't repeated
    ]
    assert "alert" not in text and "color" not in text


# -- WebFetch


def test_fetch_returns_the_address_the_title_and_the_text(ctx: ToolContext) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return html(PAGE)

    output = fetch(fetcher(handler), ctx, " https://docs.example.com/install/ ")

    assert output.content.startswith("https://docs.example.com/install/\nThe Docs\n\nHome (")
    assert "# Install" in output.content
    assert seen[0].headers["user-agent"].startswith("Zwans")


def test_fetch_follows_redirects_and_checks_each_stop(ctx: ToolContext) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "old.example.com":
            return httpx.Response(301, headers={"location": "https://new.example.com/page"})
        if request.url.path == "/page":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(200, text="plain words", headers={"content-type": "text/plain"})

    output = fetch(fetcher(handler), ctx, "http://old.example.com/")

    assert output.content == "https://new.example.com/final\n\nplain words"

    async def inside_after_a_hop(host: str) -> list[str]:
        return ["10.0.0.5"] if host == "new.example.com" else ["93.184.216.34"]

    with pytest.raises(ToolError, match=r"new\.example\.com isn't a public address"):
        fetch(fetcher(handler, inside_after_a_hop), ctx, "http://old.example.com/")


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8080/admin", "http://127.0.0.1/", "http://10.1.2.3/", "http://[::1]/"],
)
def test_fetch_only_reaches_public_addresses(ctx: ToolContext, url: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing may be sent")

    async def loopback(host: str) -> list[str]:
        return ["127.0.0.1"]

    with pytest.raises(ToolError, match="isn't a public address"):
        fetch(fetcher(handler, loopback), ctx, url)


def test_fetch_says_what_went_wrong(ctx: ToolContext) -> None:
    def missing(request: httpx.Request) -> httpx.Response:
        return html("gone", status=404)

    def image(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    async def unknown(host: str) -> list[str]:
        raise OSError("nodename nor servname provided")

    with pytest.raises(ToolError, match="HTTP 404"):
        fetch(fetcher(missing), ctx, "https://example.com/x")
    with pytest.raises(ToolError, match="image/png, which WebFetch can't read"):
        fetch(fetcher(image), ctx, "https://example.com/x.png")
    with pytest.raises(ToolError, match=r"Couldn't fetch .*connection refused"):
        fetch(fetcher(down), ctx, "https://example.com/")
    with pytest.raises(ToolError, match="Gave up after 5 redirects"):
        fetch(fetcher(loop), ctx, "https://example.com/")
    with pytest.raises(ToolError, match=r"Couldn't find nowhere\.example"):
        fetch(fetcher(missing, unknown), ctx, "https://nowhere.example/")
    with pytest.raises(ToolError, match="needs http or https"):
        fetch(fetcher(missing), ctx, "file:///etc/passwd")


def test_a_long_page_is_cut_and_says_so(ctx: ToolContext) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="word " * 20_000, headers={"content-type": "text/plain"})

    output = fetch(fetcher(handler), ctx, "https://example.com/long")

    assert len(output.content) < MAX_CHARS + 200
    assert output.content.endswith("[Only the first 60,000 of 100,000 characters are shown.]")


# -- WebSearch


def test_search_with_brave_sends_the_key_and_lists_the_results(ctx: ToolContext) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        results = [
            {"title": "<strong>Zwans</strong> docs", "url": "https://z.example/docs",
             "description": "How to &amp; why."},
            {"title": "Second", "url": "https://z.example/2", "description": ""},
            {"title": "Third", "url": "https://z.example/3"},
        ]  # fmt: skip
        return httpx.Response(200, json={"web": {"results": results}})

    config = WebSearchConfig(provider="brave")
    tool = WebSearchTool(config, {"BRAVE_API_KEY": "k-123"}, httpx.MockTransport(handler))
    output = asyncio.run(tool.run(WebSearchInput(query="zwans agent", count=2), ctx))

    assert output.content == (
        "1. Zwans docs\n   https://z.example/docs\n   How to & why.\n2. Second\n   https://z.example/2"
    )
    assert seen[0].url.host == "api.search.brave.com"
    assert (seen[0].url.params["q"], seen[0].url.params["count"]) == ("zwans agent", "2")
    assert seen[0].headers["x-subscription-token"] == "k-123"
    assert tool.host({}) == "api.search.brave.com"


def test_search_with_a_searxng_server_of_your_own(ctx: ToolContext) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("http://localhost:8888/search?")
        assert request.url.params["format"] == "json"
        found = [{"title": "A", "url": "https://a.example", "content": "About A."}]
        return httpx.Response(200, json={"results": found})

    config = WebSearchConfig(provider="searxng", url="http://localhost:8888/")
    tool = WebSearchTool(config, {}, httpx.MockTransport(handler))
    output = asyncio.run(tool.run(WebSearchInput(query="a"), ctx))

    assert output.content == "1. A\n   https://a.example\n   About A."
    assert (WebSearchTool.problem(config, {}), tool.host({})) == (None, "localhost")


def test_search_that_fails_or_finds_nothing(ctx: ToolContext) -> None:
    config = WebSearchConfig(provider="brave")

    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"web": {"results": []}})

    def run(handler: Handler) -> ToolOutput:
        tool = WebSearchTool(config, {"BRAVE_API_KEY": "k"}, httpx.MockTransport(handler))
        return asyncio.run(tool.run(WebSearchInput(query="x"), ctx))

    with pytest.raises(ToolError, match="HTTP 401"):
        run(refused)
    assert run(empty).content == "No results for 'x'."
    assert (
        WebSearchTool.problem(config, {})
        == "[web_search] uses Brave, and BRAVE_API_KEY is not set."
    )


def test_the_search_config_is_checked(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[web_search]\nprovider = "searxng"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="searxng needs url"):
        load_config(path, env={})


# -- the policy


def test_the_policy_judges_a_fetch_like_a_network_command(tmp_path: Path) -> None:
    tool = WebFetchTool()
    docs = {"url": "https://docs.python.org/3/library/re.html"}

    # It asks even in auto mode, as curl would, and "always" is for that host only.
    asked = permissions(tmp_path, "auto").check(tool, docs)
    assert (asked.decision, asked.reason) == (
        Decision.ASK,
        "WebFetch docs.python.org uses the network",
    )
    assert asked.rules == ("WebFetch(docs.python.org)",)
    refused = permissions(tmp_path, "read-only").check(tool, docs)
    assert refused.decision == Decision.DENY and "read-only mode" in refused.reason

    # Rules name hosts.
    allowed = permissions(tmp_path, "ask", allow=["WebFetch(*.python.org)"])
    assert allowed.check(tool, docs).decision == Decision.ALLOW
    assert allowed.check(tool, {"url": "https://example.com/"}).decision == Decision.ASK
    denied = permissions(tmp_path, "auto", allow=["WebFetch"], deny=["WebFetch(evil.example)"])
    assert denied.check(tool, docs).decision == Decision.ALLOW
    assert denied.check(tool, {"url": "http://evil.example/x"}).decision == Decision.DENY


def test_after_untrusted_content_a_fetch_is_judged_as_the_network_is(tmp_path: Path) -> None:
    tool = WebFetchTool()
    perms = permissions(tmp_path, "ask", allow=["WebFetch"])
    perms.tainted = True  # a file or a page has been read, and may have asked for this

    verdict = perms.check(tool, {"url": "https://example.com/?q=what-was-read"})

    assert verdict.decision == perms.policy.after_untrusted.network
    if verdict.decision != Decision.ALLOW:
        assert "after untrusted content was read" in verdict.reason
        assert verdict.rules == ()  # "always" couldn't help, so it isn't offered
    assert perms.observe("WebFetch", is_error=False) is True  # and a page is untrusted itself


# -- who is offered them


class Recorder:
    """A backend that notes which tools it was told about."""

    last_request = None

    def __init__(self) -> None:
        self.offered: list[str] = []

    def set_model(self, model: str) -> None:
        pass

    async def stream(
        self, system: str, messages: Sequence[Message], tools: Sequence[Tool[Any]]
    ) -> AsyncIterator[StreamItem]:
        self.offered = [tool.name for tool in tools]
        return
        yield  # makes this a generator, as a backend's stream is

    async def aclose(self) -> None:
        pass


def offered_to(model: str, config: Config) -> list[str]:
    backend = Recorder()

    def make(resolved: Resolved) -> Any:
        return backend

    router = ModelRouter(config, {"ANTHROPIC_API_KEY": "k"}, model, make_backend=make)
    search = WebSearchTool(WebSearchConfig(provider="searxng", url="http://localhost:1"), {})

    async def run() -> None:
        async for _ in router.stream("", [], [WebFetchTool(), search]):
            pass

    asyncio.run(run())
    return backend.offered


def test_claude_keeps_its_own_web_tools_and_other_models_get_these(tmp_path: Path) -> None:
    config = Config(home=tmp_path / "home")

    assert offered_to("claude-haiku-5-5", config) == []  # Anthropic runs its own
    assert offered_to("ollama/qwen3:8b", config) == ["WebFetch", "WebSearch"]


def test_a_session_gets_the_new_tools_unless_the_config_turns_them_off(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def names(config: Config) -> list[str]:
        opened = open_session(
            config, {}, workspace=workspace, make_provider=lambda c, m: FakeProvider([])
        )
        try:
            return [tool.name for tool in opened.session.tools]
        finally:
            asyncio.run(opened.close())

    home = tmp_path / "home"
    full = names(Config(home=home, subagents=False, todos=False))
    assert full == [
        "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "Outline", "References",
        "Rename", "Bash", "BashOutput", "KillBash", "RunTests", "Diagnostics", "Docs",
        "Python", "ShowChanges", "Memory", "WebFetch",
    ]  # fmt: skip
    # AskUser is there only when someone can be asked.
    assert "AskUser" not in full
    off = ["Outline", "References", "Rename", "RunTests", "Docs", "Python", "ShowChanges", "Memory"]
    bare = names(
        Config(
            home=home,
            subagents=False,
            todos=False,
            multi_edit=False,
            diagnostics=False,
            web=False,
            disabled_tools=off,
        )
    )
    assert bare == ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "BashOutput", "KillBash"]
    searching = Config(
        home=home, subagents=False, todos=False,
        web_search=WebSearchConfig(provider="searxng", url="http://localhost:8888"),
    )  # fmt: skip
    assert names(searching)[-2:] == ["WebFetch", "WebSearch"]
