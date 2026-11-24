# ruff: noqa: E501  (the JavaScript run in the page)
"""The Browser tool: open a page in a real browser, read it as text, and use it.

A model that writes a web app can't see whether it works. This drives a headless Chromium
through Playwright and gives the model the page the cheap way: not a screenshot (about 1,600
tokens, and hard to act on) but an outline of what's on it, the headings, text, links,
buttons and fields, each one it can act on marked with a ref, as [e7]. The model clicks or
types by ref, and every action returns the page as it is afterwards, with any console
errors and failed requests since the last one, which is often where a bug shows. A
screenshot is there for when the look itself matters, and an audit checks the open page for
common accessibility problems and reports how fast it loaded, with a script run in the page
(nothing downloaded, no axe-core).

The page stays open between calls for the rest of the session. The policy judges each call
as a request to the page's host, so `Browser(localhost)` allows them for a dev server.

Playwright is optional: `pip install 'zwans[browser]'` and `playwright install chromium`.
"""

import asyncio
import contextlib
from typing import Any, Literal

from pydantic import BaseModel, Field

from zwans.images import ImageError, image_block
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.web_local import host_of

Action = Literal[
    "open", "click", "type", "select", "press", "back", "read", "screenshot", "audit", "close"
]
TIMEOUT = 15_000  # milliseconds an action may wait for the page
MAX_OUTLINE_CHARS = 15_000
SETTLE = 3.0  # seconds an action waits, at most, for the requests it set off
QUIET = 0.3  # seconds with none open that count as settled
STEP = 0.05
MAX_EVENTS = 10  # console messages and failed requests shown after an action
AUDIT_EXAMPLES = 5  # elements shown for each kind of accessibility problem
VIEWPORT = {"width": 1280, "height": 800}
INSTALL = (
    "The Browser tool needs Playwright: pip install 'zwans[browser]' (or pip install "
    "playwright), then playwright install chromium."
)

# Marks what can be acted on with data-zwans-ref and returns the page as an outline. Runs in
# the page. Each line is indented by how deep it sits among the landmarks (nav, main, ...).
OUTLINE = r"""
() => {
  document.querySelectorAll("[data-zwans-ref]").forEach((el) => el.removeAttribute("data-zwans-ref"));
  const ACT = "a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=checkbox],[role=radio],[role=tab],[role=menuitem],[role=switch],[role=option],[role=combobox],[contenteditable=true],[onclick]";
  const LANDMARKS = { NAV: "navigation", MAIN: "main", HEADER: "header", FOOTER: "footer", ASIDE: "aside", FORM: "form", DIALOG: "dialog", TABLE: "table", UL: "list", OL: "list", SECTION: "", ARTICLE: "article" };
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "HEAD", "META", "LINK"]);
  let next = 0;
  const lines = [];
  const clip = (s, n) => { s = (s || "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  const visible = (el) => {
    if (el.checkVisibility) return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
  };
  const labelOf = (el) => {
    if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
    const by = el.getAttribute("aria-labelledby");
    if (by) { const t = by.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" "); if (t.trim()) return t; }
    if (el.labels && el.labels.length) return Array.from(el.labels).map((l) => l.innerText).join(" ");
    return "";
  };
  const describe = (el) => {
    const tag = el.tagName;
    const type = (el.getAttribute("type") || "").toLowerCase();
    const role = el.getAttribute("role");
    const ref = "e" + ++next;
    el.setAttribute("data-zwans-ref", ref);
    let kind = role || (tag === "A" ? "link" : tag === "SELECT" ? "select" : tag === "TEXTAREA" ? "textbox" : tag === "SUMMARY" ? "summary" : tag === "BUTTON" ? "button" : tag === "INPUT" ? (["checkbox", "radio"].includes(type) ? type : ["submit", "button", "reset"].includes(type) ? "button" : "textbox") : "clickable");
    let name = clip(labelOf(el) || el.innerText || el.value || el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("alt") || el.querySelector?.("img")?.getAttribute("alt") || "", 100);
    const bits = [];
    if (kind === "textbox") {
      if (el.getAttribute("placeholder") && name !== el.getAttribute("placeholder")) bits.push(`placeholder "${clip(el.getAttribute("placeholder"), 60)}"`);
      if (type && type !== "text") bits.push(type);
      if (el.value) bits.push(`value "${clip(type === "password" ? "•••" : el.value, 80)}"`);
      if (name === el.value) name = labelOf(el) || "";
    }
    if (kind === "checkbox" || kind === "radio" || role === "switch") bits.push(el.checked || el.getAttribute("aria-checked") === "true" ? "checked" : "unchecked");
    if (tag === "SELECT") {
      const options = Array.from(el.options).map((o) => clip(o.text, 40));
      bits.push(`selected "${clip(el.selectedOptions[0]?.text || "", 40)}"`);
      bits.push("options: " + options.slice(0, 12).join(" | ") + (options.length > 12 ? ` | … ${options.length - 12} more` : ""));
      name = clip(labelOf(el), 60);
    }
    if (el.disabled || el.getAttribute("aria-disabled") === "true") bits.push("disabled");
    if (el.getAttribute("aria-expanded")) bits.push(el.getAttribute("aria-expanded") === "true" ? "expanded" : "collapsed");
    if (tag === "A") { const href = el.getAttribute("href") || ""; if (href && !href.startsWith("javascript:")) bits.push("→ " + clip(href, 80)); }
    return `${kind}${name ? ` "${name}"` : ""} [${ref}]${bits.length ? " " + bits.join(", ") : ""}`;
  };
  const walk = (el, depth) => {
    if (SKIP.has(el.tagName) || !visible(el)) return;
    const pad = "  ".repeat(depth);
    if (el.matches(ACT)) { lines.push(pad + describe(el)); return; }
    if (/^H[1-6]$/.test(el.tagName)) { lines.push(`${pad}${"#".repeat(+el.tagName[1])} ${clip(el.innerText, 200)}`); return; }
    if (el.tagName === "IMG") { const alt = el.getAttribute("alt"); if (alt) lines.push(`${pad}image "${clip(alt, 100)}"`); return; }
    const landmark = LANDMARKS[el.tagName] ?? (el.getAttribute("role") && ["navigation", "main", "dialog", "alert", "banner", "contentinfo", "search", "status"].includes(el.getAttribute("role")) ? el.getAttribute("role") : undefined);
    if (landmark) {
      const name = clip(el.getAttribute("aria-label") || "", 60);
      if (landmark && landmark !== "list") lines.push(`${pad}${landmark}${name ? ` "${name}"` : ""}:`);
      for (const child of el.children) walk(child, depth + (landmark && landmark !== "list" ? 1 : 0));
      return;
    }
    if (el.tagName === "LI" && !el.querySelector(ACT)) { const t = clip(el.innerText, 300); if (t) lines.push(`${pad}- ${t}`); return; }
    if (el.tagName === "TR" && !el.querySelector(ACT)) { const t = Array.from(el.children).map((c) => clip(c.innerText, 60)).join(" | "); if (t.trim()) lines.push(`${pad}| ${t}`); return; }
    if (!el.querySelector(ACT) && !el.querySelector("h1,h2,h3,h4,h5,h6,img[alt],li,tr")) {
      const t = clip(el.innerText, 400);
      if (t) lines.push(pad + t);
      return;
    }
    // A mix: its own text, then its children.
    const own = Array.from(el.childNodes).filter((n) => n.nodeType === 3).map((n) => n.textContent).join(" ");
    if (clip(own, 10)) lines.push(pad + clip(own, 300));
    for (const child of el.children) walk(child, depth);
  };
  if (document.body) for (const child of document.body.children) walk(child, 0);
  return lines.join("\n");
}
"""


# Checks the open page for common accessibility problems and measures how it loaded. Runs in
# the page and returns {checks: [{title, count, examples}], perf: {...}}. Each example names
# the element, with its ref when the outline gave it one. Contrast is checked only where the
# background is plain colors all the way up, since an image or gradient can't be measured.
AUDIT = r"""
async (MAX) => {
  const clip = (s, n) => { s = (s || "").replace(/\s+/g, " ").trim(); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
  const visible = (el) => {
    if (el.closest("[aria-hidden=true]")) return false;
    if (el.checkVisibility) return el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
  };
  const describe = (el, note) => {
    let s = "<" + el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    const cls = typeof el.className === "string" ? el.className.trim().split(/\s+/).filter(Boolean).slice(0, 2) : [];
    if (cls.length) s += "." + cls.join(".");
    for (const a of ["type", "name", "src", "href", "role"]) { const v = el.getAttribute(a); if (v) s += ` ${a}="${clip(v, 50)}"`; }
    s += ">";
    if (note) s += " " + note;
    else { const t = clip(el.innerText || el.value || "", 40); if (t) s += ` "${t}"`; }
    const ref = el.getAttribute("data-zwans-ref");
    return ref ? `${s} [${ref}]` : s;
  };
  const checks = [];
  const add = (title, items, note) => checks.push({
    title, count: items.length,
    examples: items.slice(0, MAX).map((el) => typeof el === "string" ? el : describe(el, note ? note(el) : "")),
  });
  const byIds = (el, attr) => (el.getAttribute(attr) || "").split(/\s+/).filter(Boolean).map((id) => document.getElementById(id)?.textContent || "").join(" ").trim();
  const nameOf = (el) => {
    const label = (el.getAttribute("aria-label") || "").trim() || byIds(el, "aria-labelledby");
    if (label) return label;
    if (el.tagName === "INPUT") {
      if (el.type === "image") return el.getAttribute("alt") || el.getAttribute("title") || "";
      if (["submit", "reset"].includes(el.type)) return el.value || el.type;
      if (el.type === "button") return el.value || el.getAttribute("title") || "";
    }
    const text = (el.innerText || el.textContent || "").trim();
    if (text) return text;
    const inner = Array.from(el.querySelectorAll("img[alt], [aria-label], svg title")).map((n) => n.getAttribute("alt") || n.getAttribute("aria-label") || n.textContent || "").join(" ").trim();
    return inner || el.getAttribute("title") || "";
  };
  const all = (selector) => Array.from(document.querySelectorAll(selector)).filter(visible);

  add("Images without alt text", [
    ...all("img:not([alt]), input[type=image]:not([alt])"),
    ...all("[role=img]").filter((el) => !nameOf(el)),
  ]);
  add("Buttons and links with no accessible name",
    all("a[href], button, [role=button], [role=link], input[type=button], input[type=submit], input[type=reset]").filter((el) => !nameOf(el)));
  const fields = all("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea")
    .filter((el) => !(el.getAttribute("aria-label") || "").trim() && !byIds(el, "aria-labelledby") && !(el.labels && Array.from(el.labels).some((l) => l.textContent.trim())) && !el.getAttribute("title"));
  add("Form fields without a label", fields, (el) => el.getAttribute("placeholder") ? `(placeholder "${clip(el.getAttribute("placeholder"), 40)}" only)` : "");
  add("Page language missing", (document.documentElement.getAttribute("lang") || "").trim() ? [] : ["<html> has no lang attribute"]);
  add("Page title missing", document.title.trim() ? [] : ["<title> is missing or empty"]);

  const skips = [];
  let previous = 0;
  for (const h of all("h1, h2, h3, h4, h5, h6, [role=heading][aria-level]")) {
    const level = /^H[1-6]$/.test(h.tagName) ? +h.tagName[1] : +h.getAttribute("aria-level");
    if (previous && level > previous + 1) skips.push(describe(h, `"${clip(h.innerText, 40)}" comes after an h${previous}`));
    previous = level;
  }
  add("Heading levels that skip", skips);

  const ids = new Map();
  for (const el of document.querySelectorAll("[id]")) ids.set(el.id, (ids.get(el.id) || 0) + 1);
  add("Duplicate ids", Array.from(ids).filter(([id, n]) => id && n > 1).map(([id, n]) => `id "${clip(id, 40)}" is used ${n} times`));

  const parse = (value) => {
    const m = /^rgba?\(([^)]+)\)$/.exec(value || "");
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (top, under) => ({ r: top.r * top.a + under.r * (1 - top.a), g: top.g * top.a + under.g * (1 - top.a), b: top.b * top.a + under.b * (1 - top.a), a: 1 });
  const background = (el) => {
    const layers = [];
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage && style.backgroundImage !== "none") return null;
      const color = parse(style.backgroundColor);
      if (color === null) return null;
      if (color.a > 0) { layers.push(color); if (color.a >= 1) break; }
    }
    let base = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of layers.reverse()) base = over(layer, base);
    return base;
  };
  const luminance = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const hex = (c) => "#" + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
  const low = [];
  let checked = 0;
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "OPTION"]);
  for (const el of document.body ? document.body.querySelectorAll("*") : []) {
    if (checked >= 3000) break;
    if (SKIP.has(el.tagName)) continue;
    if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
    if (!visible(el)) continue;
    checked++;
    const style = getComputedStyle(el);
    const bg = background(el);
    const fg = parse(style.color);
    if (!bg || !fg) continue;
    const text = over(fg, bg);
    const [a, b] = [luminance(text), luminance(bg)].sort((x, y) => y - x);
    const ratio = (a + 0.05) / (b + 0.05);
    const size = parseFloat(style.fontSize);
    const large = size >= 24 || (size >= 18.66 && (parseInt(style.fontWeight) || 400) >= 700);
    const needed = large ? 3 : 4.5;
    if (ratio < needed) low.push(describe(el, `"${clip(el.innerText, 30)}" ${ratio.toFixed(2)}:1 (${hex(text)} on ${hex(bg)}), needs ${needed}:1`));
  }
  add("Text with low contrast", low);
  add("Positive tabindex", all("[tabindex]").filter((el) => parseInt(el.getAttribute("tabindex")) > 0), (el) => `tabindex=${el.getAttribute("tabindex")}`);

  const observe = (type) => new Promise((resolve) => {
    const found = [];
    try {
      const observer = new PerformanceObserver((list) => found.push(...list.getEntries()));
      observer.observe({ type, buffered: true });
      setTimeout(() => { found.push(...observer.takeRecords()); observer.disconnect(); resolve(found); }, 150);
    } catch (e) { resolve(null); }
  });
  const [paints, shifts] = await Promise.all([observe("largest-contentful-paint"), observe("layout-shift")]);
  const nav = performance.getEntriesByType("navigation")[0];
  const fcp = performance.getEntriesByName("first-contentful-paint")[0];
  const lcp = paints && paints.length ? paints[paints.length - 1] : null;
  const resources = performance.getEntriesByType("resource");
  const sizeOf = (e) => Math.max(e.transferSize || 0, e.encodedBodySize || 0);
  const perf = {
    ttfb: nav ? nav.responseStart - nav.startTime : null,
    fcp: fcp ? fcp.startTime : null,
    dcl: nav ? nav.domContentLoadedEventEnd - nav.startTime : null,
    load: nav && nav.loadEventEnd ? nav.loadEventEnd - nav.startTime : null,
    lcp: lcp ? lcp.startTime : null,
    lcpElement: lcp && lcp.element ? describe(lcp.element, lcp.url ? clip(lcp.url, 80) : "") : (lcp && lcp.url ? clip(lcp.url, 80) : ""),
    cls: shifts ? shifts.filter((e) => !e.hadRecentInput).reduce((sum, e) => sum + e.value, 0) : null,
    requests: resources.length + (nav ? 1 : 0),
    bytes: resources.reduce((sum, e) => sum + sizeOf(e), 0) + (nav ? sizeOf(nav) : 0),
    document: nav ? sizeOf(nav) : 0,
    largest: resources.map((e) => ({ url: e.name, type: e.initiatorType, size: sizeOf(e), ms: e.duration })).sort((x, y) => y.size - x.size).slice(0, 5),
    full: resources.length >= 250,
  };
  return { checks, perf };
}
"""


class BrowserInput(BaseModel):
    action: Action = Field(
        description="open a url; click, type into or select in an element by its ref; press a "
        "key; back; read the page again; take a screenshot; audit the page for accessibility "
        "problems and load performance; or close the browser."
    )
    url: str | None = Field(
        default=None, description='For open: the address, as "http://localhost:3000".'
    )
    ref: str | None = Field(
        default=None, description='The element to act on, as "e7", from the outline.'
    )
    text: str | None = Field(
        default=None,
        description="For type: the text to enter. For select: the option's label or value.",
    )
    key: str | None = Field(
        default=None, description='For press: a key, as "Enter", "Escape" or "Tab".'
    )
    submit: bool = Field(default=False, description="For type: press Enter afterwards.")
    full_page: bool = Field(
        default=False, description="For screenshot: the whole page, not just the window."
    )


class BrowserTool:
    name = "Browser"
    description = (
        "Use a web page in a real browser (headless Chromium), such as the app you're "
        "building on localhost. Every action returns the page as an outline: headings, text, "
        "links, buttons and fields, each you can act on marked with a ref like [e7], plus "
        "console errors and failed requests since the last action. open a url, then click, "
        "type, select or press by ref. Take a screenshot only when the look matters; the "
        "outline is much cheaper. audit checks the open page for accessibility problems "
        "(missing alt text, unnamed buttons and links, unlabeled fields, low contrast, "
        "skipped heading levels, duplicate ids) and reports how fast it loaded (time to "
        "first byte, LCP, layout shift, requests and the largest ones). The page stays open "
        "between calls."
    )
    input_model = BrowserInput
    read_only = False  # clicking can change things

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None
        self._events: list[str] = []
        self._inflight = 0  # requests the page has open
        self._lock = asyncio.Lock()

    def host(self, args: dict[str, Any]) -> str:
        """Where the call acts, for the policy: the address it opens, or the open page's."""
        if args.get("action") == "close":
            return ""
        url = args.get("url") if args.get("action") == "open" else None
        if url is None and self._page is not None:
            url = self._page.url
        return host_of(url)

    async def run(self, args: BrowserInput, ctx: ToolContext) -> ToolOutput:
        async with self._lock:
            if args.action == "close":
                had = self._page is not None
                await self.aclose()
                return ToolOutput(
                    content="Closed the browser." if had else "The browser wasn't open."
                )
            if args.action == "open":
                if not args.url or not host_of(args.url):
                    raise ToolError("open needs a url starting with http:// or https://.")
                page = await self._ensure()
                await self._goto(page, args.url)
                return await self._outline()
            page = self._page
            if page is None:
                raise ToolError("Nothing is open yet: use action open with a url first.")
            if args.action == "read":
                return await self._outline()
            if args.action == "screenshot":
                return await self._screenshot(args.full_page)
            if args.action == "audit":
                return await self._audit()
            if args.action == "back":
                await page.go_back(timeout=TIMEOUT)
            elif args.action == "press":
                if not args.key:
                    raise ToolError("press needs a key, as Enter.")
                target = self._element(args.ref) if args.ref else page.keyboard
                await target.press(args.key, **({"timeout": TIMEOUT} if args.ref else {}))
            else:
                element = self._element(args.ref)
                await self._act(element, args)
            await self._settle(page)
            return await self._outline()

    async def _act(self, element: Any, args: BrowserInput) -> None:
        from playwright.async_api import Error as PlaywrightError

        try:
            if args.action == "click":
                await element.click(timeout=TIMEOUT)
            elif args.action == "type":
                if args.text is None:
                    raise ToolError("type needs text.")
                await element.fill(args.text, timeout=TIMEOUT)
                if args.submit:
                    await element.press("Enter", timeout=TIMEOUT)
            elif args.action == "select":
                if args.text is None:
                    raise ToolError("select needs text: the option's label or value.")
                try:
                    await element.select_option(label=args.text, timeout=TIMEOUT)
                except PlaywrightError:
                    await element.select_option(value=args.text, timeout=TIMEOUT)
        except PlaywrightError as exc:
            raise ToolError(f"Couldn't {args.action} {args.ref}: {_first_line(exc)}") from exc

    def _element(self, ref: str | None) -> Any:
        if not ref:
            raise ToolError("This action needs a ref, as e7, from the page's outline.")
        ref = ref.strip().strip("[]")
        return self._page.locator(f'[data-zwans-ref="{ref}"]').first

    async def _ensure(self) -> Any:
        if self._page is not None and not self._page.is_closed():
            return self._page
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ToolError(INSTALL) from None
        from playwright.async_api import Error as PlaywrightError

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            await self.aclose()
            raise ToolError(f"Chromium didn't start ({_first_line(exc)}). {INSTALL}") from exc
        context = await self._browser.new_context(viewport=VIEWPORT)
        page = await context.new_page()
        page.on("console", self._on_console)
        page.on("pageerror", lambda error: self._events.append(f"page error: {_first_line(error)}"))
        page.on("requestfailed", self._on_failed)
        page.on("response", self._on_response)
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_finished)
        self._page = page
        return page

    def _on_request(self, request: Any) -> None:
        self._inflight += 1

    def _on_finished(self, request: Any) -> None:
        self._inflight = max(self._inflight - 1, 0)

    def _on_console(self, message: Any) -> None:
        if message.type in ("error", "warning"):
            self._events.append(f"console {message.type}: {message.text[:300]}")

    def _on_failed(self, request: Any) -> None:
        self._inflight = max(self._inflight - 1, 0)
        failure = request.failure or "failed"
        self._events.append(f"request failed: {request.method} {request.url[:200]} ({failure})")

    def _on_response(self, response: Any) -> None:
        if response.status >= 400:
            request = response.request
            self._events.append(f"HTTP {response.status}: {request.method} {response.url[:200]}")

    async def _goto(self, page: Any, url: str) -> None:
        from playwright.async_api import Error as PlaywrightError

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT)
        except PlaywrightError as exc:
            message = _first_line(exc)
            if "ERR_CONNECTION_REFUSED" in message:
                raise ToolError(f"Nothing answered at {url}: is the server running?") from exc
            raise ToolError(f"Couldn't open {url}: {message}") from exc
        await self._settle(page)

    async def _settle(self, page: Any) -> None:
        """Wait for what an action set off: until no request has been open for a moment, or
        SETTLE seconds at most, since a page that keeps a connection open never goes quiet.
        (Playwright's own "networkidle" is about the page's first load, not later requests.)"""
        quiet = 0.0
        waited = 0.0
        while waited < SETTLE and quiet < QUIET:
            await asyncio.sleep(STEP)
            waited += STEP
            quiet = quiet + STEP if self._inflight == 0 else 0.0

    async def _outline(self) -> ToolOutput:
        page = self._page
        try:
            outline = await page.evaluate(OUTLINE)
            title = await page.title()
        except Exception as exc:
            raise ToolError(f"Couldn't read the page: {_first_line(exc)}") from exc
        if len(outline) > MAX_OUTLINE_CHARS:
            outline = outline[:MAX_OUTLINE_CHARS] + "\n[... the rest of the page isn't shown]"
        lines = [
            f"{title or '(no title)'} — {page.url}",
            "",
            outline or "(The page shows nothing.)",
        ]
        lines += self._take_events()
        return ToolOutput(content="\n".join(lines))

    def _take_events(self) -> list[str]:
        events, self._events = self._events, []
        if not events:
            return []
        shown = list(dict.fromkeys(events))[:MAX_EVENTS]
        more = len(events) - len(shown)
        return ["", "Since the last action:", *[f"- {e}" for e in shown]] + (
            [f"- and {more} more"] if more > 0 else []
        )

    async def _screenshot(self, full_page: bool) -> ToolOutput:
        data = await self._page.screenshot(full_page=full_page, type="jpeg", quality=80)
        try:
            image = image_block(data, "the screenshot")
        except ImageError as exc:
            raise ToolError(f"{exc} Take one of the window instead of the full page.") from exc
        size = (
            "the whole page"
            if full_page
            else f"the window ({VIEWPORT['width']}x{VIEWPORT['height']})"
        )
        lines = [f"A screenshot of {size}: {self._page.url}", *self._take_events()]
        return ToolOutput(content="\n".join(lines), images=(image,))

    async def _audit(self) -> ToolOutput:
        page = self._page
        try:
            found = await page.evaluate(AUDIT, AUDIT_EXAMPLES)
            title = await page.title()
        except Exception as exc:
            raise ToolError(f"Couldn't audit the page: {_first_line(exc)}") from exc
        lines = [f"Audit of {title or '(no title)'} — {page.url}", ""]
        lines += _accessibility(found.get("checks") or [])
        lines += ["", *_performance(found.get("perf") or {})]
        lines += self._take_events()
        return ToolOutput(content="\n".join(lines))

    async def aclose(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = self._playwright = self._page = None
        self._events = []
        self._inflight = 0
        if browser is not None:
            with contextlib.suppress(Exception):
                await browser.close()
        if playwright is not None:
            with contextlib.suppress(Exception):
                await playwright.stop()


def available() -> bool:
    """Whether Playwright is installed, so the tool can be offered."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _accessibility(checks: list[dict[str, Any]]) -> list[str]:
    failed = [c for c in checks if c.get("count")]
    total = sum(int(c["count"]) for c in failed)
    if not failed:
        lines = [f"Accessibility: no problems found by {len(checks)} checks."]
    else:
        lines = [
            f"Accessibility: {total} problem{'s' if total != 1 else ''} in "
            f"{len(failed)} of {len(checks)} checks."
        ]
    for check in failed:
        examples = check.get("examples") or []
        lines.append(f"- {check['title']}: {check['count']}")
        lines += [f"    {example}" for example in examples]
        more = int(check["count"]) - len(examples)
        if more > 0:
            lines.append(f"    and {more} more")
    passed = [c["title"] for c in checks if not c.get("count")]
    if failed and passed:
        lines.append("No problems: " + "; ".join(t[0].lower() + t[1:] for t in passed) + ".")
    lines.append(
        "(Contrast is checked only where the text's background is a plain color, not an image "
        "or gradient; large text needs 3:1, other text 4.5:1.)"
    )
    return lines


def _performance(perf: dict[str, Any]) -> list[str]:
    timings = [
        ("time to first byte", perf.get("ttfb")),
        ("first contentful paint", perf.get("fcp")),
        ("DOMContentLoaded", perf.get("dcl")),
        ("load", perf.get("load")),
    ]
    shown = [f"{name} {_ms(value)}" for name, value in timings if value is not None]
    lines = ["Performance (the page's load, in this headless browser):"]
    if shown:
        lines.append("  " + ", ".join(shown))
    if perf.get("load") is None:
        lines.append("  The load event hasn't fired yet.")
    if perf.get("lcp") is not None:
        element = perf.get("lcpElement")
        where = f": {element}" if element else ""
        lines.append(f"  Largest contentful paint {_ms(perf['lcp'])}{where}")
    if perf.get("cls") is not None:
        lines.append(f"  Cumulative layout shift {perf['cls']:.3f}")
    requests = int(perf.get("requests") or 0)
    more = "+" if perf.get("full") else ""
    total = _bytes(int(perf.get("bytes") or 0))
    document = _bytes(int(perf.get("document") or 0))
    plural = "s" if requests != 1 else ""
    lines.append(f"  {requests}{more} request{plural}, {total} (the document {document})")
    largest = [r for r in perf.get("largest") or [] if r.get("size")]
    if largest:
        lines.append("  Largest:")
        for resource in largest:
            kind = str(resource.get("type") or "?")
            lines.append(
                f"    {_bytes(int(resource['size'])):>9}  {kind:<8} "
                f"{str(resource.get('url'))[:150]}  ({_ms(resource.get('ms'))})"
            )
    lines.append(
        "  (Sizes are as transferred; a cross-origin resource without Timing-Allow-Origin "
        "counts as 0.)"
    )
    return lines


def _ms(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "?"
    return f"{value / 1000:.2f} s" if value >= 1000 else f"{value:.0f} ms"


def _bytes(size: int) -> str:
    if size < 1000:
        return f"{size} B"
    if size < 1_000_000:
        return f"{size / 1000:.1f} KB"
    return f"{size / 1_000_000:.1f} MB"


def _first_line(error: object) -> str:
    text = str(error).strip()
    return text.splitlines()[0] if text else type(error).__name__
