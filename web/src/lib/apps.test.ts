import { describe, expect, it, vi } from "vitest";
import { AppBridge, buildCsp, parseApp, themeVariables, viewDocument, type AppHost, type AppView } from "./apps";
import { buildTurns } from "./events";

const RAW_APP = {
  server: "charts",
  tool: { name: "chart", inputSchema: { type: "object" } },
  arguments: { numbers: [4, 2] },
  result: { content: [{ type: "text", text: "numbers: [4, 2]" }], structuredContent: { numbers: [4, 2] } },
  uri: "ui://charts/view.html",
  html: "<!doctype html><p>chart</p>",
  csp: { resourceDomains: ["https://cdn.example.com", "x; script-src *"], connectDomains: [] },
  permissions: ["clipboardWrite", "camera"],
  prefers_border: true,
};

const view = (): AppView => parseApp(RAW_APP)!;

function bridged(overrides: Partial<AppHost> = {}) {
  const sent: Record<string, unknown>[] = [];
  const host: AppHost = {
    callTool: vi.fn(async () => ({ content: [{ type: "text", text: "called" }] })),
    readResource: vi.fn(async () => ({ contents: [] })),
    openLink: vi.fn(),
    message: vi.fn(),
    resize: vi.fn(),
    ...overrides,
  };
  const bridge = new AppBridge(view(), host, (m) => sent.push({ ...m }), {
    theme: "light",
    variables: { "--color-text-primary": "#111" },
    locale: "en-GB",
  });
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
  return { bridge, host, sent, flush };
}

describe("tool results with a view", () => {
  it("are parsed from the tool_result event onto the call", () => {
    const [turn] = buildTurns([
      { type: "turn_started", prompt: "Chart it." },
      { type: "tool_call_requested", call_id: "c1", name: "mcp__charts__chart", args: { numbers: [4, 2] } },
      { type: "tool_result", call_id: "c1", content: "numbers: [4, 2]", untrusted: true, app: RAW_APP },
      { type: "tool_call_requested", call_id: "view_1", name: "mcp__charts__shuffle", args: {}, by: "view" },
      { type: "tool_result", call_id: "view_1", content: "numbers: [2, 4]", app: null },
    ]);
    const [chart, shuffle] = turn!.items.map((item) => (item.kind === "tool" ? item.call : null));
    expect(chart?.byView).toBeUndefined();
    expect(chart?.result?.app).toEqual({
      server: "charts",
      tool: RAW_APP.tool,
      arguments: { numbers: [4, 2] },
      result: RAW_APP.result,
      uri: "ui://charts/view.html",
      html: "<!doctype html><p>chart</p>",
      // What could add a directive of its own is dropped.
      csp: { connectDomains: [], resourceDomains: ["https://cdn.example.com"], frameDomains: [], baseUriDomains: [] },
      permissions: ["clipboardWrite", "camera"],
      prefersBorder: true,
    });
    expect(shuffle?.byView).toBe(true);
    expect(shuffle?.result?.app).toBeUndefined();
    expect(parseApp({ uri: "ui://x" })).toBeNull(); // no HTML, no view
  });
});

describe("the view's sandbox", () => {
  it("allows only what the server declared", () => {
    expect(buildCsp({})).toBe(
      "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; " +
        "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' data: blob:; connect-src 'none'; " +
        "frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'",
    );
    const csp = buildCsp({ resourceDomains: ["https://cdn.example.com"], connectDomains: ["https://api.example.com"] });
    expect(csp).toContain("script-src 'self' 'unsafe-inline' https://cdn.example.com;");
    expect(csp).toContain("connect-src 'self' https://api.example.com;");
  });

  it("puts the policy before anything of the view's own", () => {
    expect(viewDocument("<!DOCTYPE html><html><head><script>1</script>", {})).toMatch(
      /^<!DOCTYPE html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; [^"]+"><html><head><script>/,
    );
    expect(viewDocument("<p>no doctype</p>", {})).toMatch(/^<meta http-equiv="Content-Security-Policy" [^>]+><p>no doctype/);
  });

  it("maps Zwans's tokens to the spec's style variables", () => {
    const tokens: Record<string, string> = { "--ink": " #1d1d1f", "--base": "#ecece9", "--warn": "#8a5a00", "--sans": "Inter" };
    const vars = themeVariables((name) => tokens[name] ?? "");
    expect(vars["--color-text-primary"]).toBe("#1d1d1f");
    expect(vars["--color-background-primary"]).toBe("#ecece9");
    expect(vars["--color-background-warning"]).toBe("color-mix(in srgb, #8a5a00 14%, transparent)");
    expect(vars["--font-sans"]).toBe("Inter");
    expect(vars["--font-heading-3xl-size"]).toBe("36px");
  });
});

describe("AppBridge", () => {
  it("answers initialize, then sends the arguments and the result once the view is ready", async () => {
    const { bridge, sent, flush } = bridged();
    bridge.receive({
      jsonrpc: "2.0",
      id: 1,
      method: "ui/initialize",
      params: { appInfo: { name: "chart", version: "1" }, appCapabilities: {}, protocolVersion: "2026-01-26" },
    });
    await flush();
    expect(sent).toHaveLength(1); // nothing unasked before "initialized"
    const result = sent[0]!.result as Record<string, Record<string, unknown>>;
    expect(sent[0]).toMatchObject({ jsonrpc: "2.0", id: 1 });
    expect(result.protocolVersion).toBe("2026-01-26");
    expect(result.hostInfo).toMatchObject({ name: "zwans" });
    expect(result.hostCapabilities).toMatchObject({
      serverTools: {},
      openLinks: {},
      message: { text: {} },
      sandbox: { permissions: { clipboardWrite: {} } }, // not the camera it asked for
    });
    expect(result.hostContext).toMatchObject({
      toolInfo: { tool: RAW_APP.tool },
      theme: "light",
      styles: { variables: { "--color-text-primary": "#111" } },
      displayMode: "inline",
      locale: "en-GB",
    });

    bridge.receive({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
    bridge.receive({ jsonrpc: "2.0", method: "ui/notifications/initialized" }); // once is enough
    expect(sent.slice(1)).toEqual([
      { jsonrpc: "2.0", method: "ui/notifications/tool-input", params: { arguments: { numbers: [4, 2] } } },
      { jsonrpc: "2.0", method: "ui/notifications/tool-result", params: RAW_APP.result },
    ]);
  });

  it("passes the view's tool calls and reads to the session, and its errors back", async () => {
    const callTool = vi.fn(async () => {
      throw new Error("The policy refused it");
    });
    const { bridge, host, sent, flush } = bridged({ callTool });
    bridge.receive({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "shuffle", arguments: { n: 1 } } });
    bridge.receive({ jsonrpc: "2.0", id: 3, method: "resources/read", params: { uri: "ui://charts/data" } });
    bridge.receive({ jsonrpc: "2.0", id: 4, method: "tools/call", params: {} });
    await flush();
    expect(callTool).toHaveBeenCalledWith("shuffle", { n: 1 });
    expect(host.readResource).toHaveBeenCalledWith("ui://charts/data");
    sent.sort((a, b) => Number(a.id) - Number(b.id)); // each answers when it's done
    expect(sent).toEqual([
      { jsonrpc: "2.0", id: 2, error: { code: -32000, message: "The policy refused it" } },
      { jsonrpc: "2.0", id: 3, result: { contents: [] } },
      { jsonrpc: "2.0", id: 4, error: { code: -32602, message: "tools/call needs a tool name" } },
    ]);
  });

  it("drafts messages, opens only web links, sizes the frame and refuses what it doesn't know", async () => {
    const { bridge, host, sent, flush } = bridged();
    const content = [{ type: "text", text: "Chart the next quarter too." }];
    bridge.receive({ jsonrpc: "2.0", id: 1, method: "ui/message", params: { role: "user", content } });
    bridge.receive({ jsonrpc: "2.0", id: 2, method: "ui/open-link", params: { url: "https://example.com/a" } });
    bridge.receive({ jsonrpc: "2.0", id: 3, method: "ui/open-link", params: { url: "javascript:alert(1)" } });
    bridge.receive({ jsonrpc: "2.0", id: 4, method: "ui/request-display-mode", params: { mode: "fullscreen" } });
    bridge.receive({ jsonrpc: "2.0", id: 5, method: "ui/update-model-context", params: {} });
    bridge.receive({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { width: 300, height: 5000 } });
    bridge.receive({ method: "tools/call", id: 6 }); // not JSON-RPC 2.0: ignored
    await flush();
    sent.sort((a, b) => Number(a.id) - Number(b.id));
    expect(host.message).toHaveBeenCalledWith("Chart the next quarter too.");
    expect(host.openLink).toHaveBeenCalledExactlyOnceWith("https://example.com/a");
    expect(host.resize).toHaveBeenCalledWith(800); // capped
    expect(sent.map((m) => [m.id, m.result ?? (m.error as { code: number }).code])).toEqual([
      [1, {}],
      [2, {}],
      [3, -32000],
      [4, { mode: "inline" }],
      [5, -32601],
    ]);
  });

  it("tells a ready view when the theme changes, and when it's going away", () => {
    const { bridge, sent } = bridged();
    bridge.setContext({ theme: "dark", variables: { "--color-text-primary": "#eee" } });
    bridge.teardown("closed");
    expect(sent).toEqual([]); // not initialized yet
    bridge.receive({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
    sent.length = 0;
    bridge.setContext({ theme: "light", variables: { "--color-text-primary": "#111" } });
    bridge.setContext({ theme: "light", variables: { "--color-text-primary": "#111" } }); // no change
    bridge.teardown("closed");
    expect(sent).toEqual([
      {
        jsonrpc: "2.0",
        method: "ui/notifications/host-context-changed",
        params: { theme: "light", styles: { variables: { "--color-text-primary": "#111" } } },
      },
      { jsonrpc: "2.0", id: "teardown-1", method: "ui/resource-teardown", params: { reason: "closed" } },
    ]);
  });
});
