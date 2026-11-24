/**
 * MCP Apps: an MCP tool's interactive view of its result (src/zwans/mcp/apps.py has the
 * server side). The view is HTML from the tool's server; it runs in an iframe sandboxed to
 * scripts only, so it has no origin of its own (no cookies, storage or Zwans's API) and its
 * CSP allows only what the server declared. It talks to Zwans over postMessage in JSON-RPC:
 * this file is that conversation, and components/AppView.tsx is the iframe.
 *
 * The spec: https://github.com/modelcontextprotocol/ext-apps (2026-01-26). Zwans hosts a view
 * inline only, and passes a view's messages to the composer as a draft rather than sending
 * them, so the person decides what goes to the model.
 */

export const PROTOCOL_VERSION = "2026-01-26";
const MAX_HEIGHT = 800; // px a view may grow to before it scrolls

/** What a tool_result event's `app` carries. */
export interface AppView {
  server: string;
  /** The tool's definition from its server, as the view is told about it. */
  tool: Record<string, unknown>;
  arguments: Record<string, unknown>;
  /** The server's whole CallToolResult: content, structuredContent, _meta. */
  result: Record<string, unknown>;
  uri: string;
  html: string;
  csp: Partial<Record<CspKey, string[]>>;
  permissions: string[];
  prefersBorder: boolean | null;
}

type CspKey = "connectDomains" | "resourceDomains" | "frameDomains" | "baseUriDomains";

const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && /^[^\s;,'"]+$/.test(item)) : [];

export function parseApp(raw: unknown): AppView | null {
  const app = obj(raw);
  if (typeof app.html !== "string" || typeof app.uri !== "string") return null;
  const csp = obj(app.csp);
  return {
    server: String(app.server ?? ""),
    tool: obj(app.tool),
    arguments: obj(app.arguments),
    result: obj(app.result),
    uri: app.uri,
    html: app.html,
    csp: {
      connectDomains: strings(csp.connectDomains),
      resourceDomains: strings(csp.resourceDomains),
      frameDomains: strings(csp.frameDomains),
      baseUriDomains: strings(csp.baseUriDomains),
    },
    permissions: strings(app.permissions),
    prefersBorder: typeof app.prefers_border === "boolean" ? app.prefers_border : null,
  };
}

/**
 * The view's Content Security Policy, from the origins its server declared, as the spec
 * builds it. A view that declared none may load nothing from the network.
 */
export function buildCsp(csp: AppView["csp"]): string {
  const join = (base: string, extra: string[] = []) => [base, ...extra].join(" ");
  const resources = csp.resourceDomains ?? [];
  const connect = csp.connectDomains ?? [];
  return [
    "default-src 'none'",
    join("script-src 'self' 'unsafe-inline'", resources),
    join("style-src 'self' 'unsafe-inline'", resources),
    join("img-src 'self' data: blob:", resources),
    join("font-src 'self' data:", resources),
    join("media-src 'self' data: blob:", resources),
    connect.length ? join("connect-src 'self'", connect) : "connect-src 'none'",
    csp.frameDomains?.length ? `frame-src ${csp.frameDomains.join(" ")}` : "frame-src 'none'",
    "object-src 'none'",
    csp.baseUriDomains?.length ? `base-uri ${csp.baseUriDomains.join(" ")}` : "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
}

const escapeAttribute = (text: string) =>
  text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * The view's HTML with its CSP as the first thing in it, so it applies before any of the
 * view's own markup. Right after the doctype the parser puts it in <head>, whatever the
 * page's own <html> and <head> tags say, and a later policy can only tighten it.
 */
export function viewDocument(html: string, csp: AppView["csp"]): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeAttribute(buildCsp(csp))}">`;
  const doctype = /^\s*(<!--[\s\S]*?-->\s*)*<!doctype[^>]*>/i.exec(html);
  const at = doctype ? doctype[0].length : 0;
  return html.slice(0, at) + meta + html.slice(at);
}

/** The iframe's `allow`: of what a view may ask for, Zwans grants only writing to the
 * clipboard. Camera, microphone and location would be asked for in Zwans's name. */
export function allowed(permissions: string[]): string[] {
  return permissions.includes("clipboardWrite") ? ["clipboardWrite"] : [];
}

/** Zwans's theme as the spec's style variables, from the tokens in globals.css. `token`
 * reads one, already resolved, as getComputedStyle does. */
export function themeVariables(token: (name: string) => string): Record<string, string> {
  const t = (name: string) => token(name).trim();
  const mix = (color: string, percent: number) => `color-mix(in srgb, ${color} ${percent}%, transparent)`;
  const ink = t("--ink");
  const ink2 = t("--ink-2");
  const base = t("--base");
  const accent = t("--accent");
  const ok = t("--ok");
  const bad = t("--bad");
  const warn = t("--warn");
  const edge = t("--edge");
  const shadow = t("--shadow");
  const vars: Record<string, string> = {
    "--color-background-primary": base,
    "--color-background-secondary": t("--raised"),
    "--color-background-tertiary": t("--code"),
    "--color-background-inverse": ink,
    "--color-background-ghost": "transparent",
    "--color-background-info": t("--accent-soft"),
    "--color-background-danger": t("--bad-soft"),
    "--color-background-success": t("--ok-soft"),
    "--color-background-warning": mix(warn, 14),
    "--color-background-disabled": t("--code"),
    "--color-text-primary": ink,
    "--color-text-secondary": ink2,
    "--color-text-tertiary": mix(ink2, 75),
    "--color-text-inverse": base,
    "--color-text-info": accent,
    "--color-text-danger": bad,
    "--color-text-success": ok,
    "--color-text-warning": warn,
    "--color-text-disabled": mix(ink2, 60),
    "--color-text-ghost": ink2,
    "--color-border-primary": mix(ink, 22),
    "--color-border-secondary": edge,
    "--color-border-tertiary": edge,
    "--color-border-inverse": base,
    "--color-border-ghost": "transparent",
    "--color-border-info": accent,
    "--color-border-danger": bad,
    "--color-border-success": ok,
    "--color-border-warning": warn,
    "--color-border-disabled": edge,
    "--color-ring-primary": accent,
    "--color-ring-secondary": ink2,
    "--color-ring-inverse": base,
    "--color-ring-info": accent,
    "--color-ring-danger": bad,
    "--color-ring-success": ok,
    "--color-ring-warning": warn,
    "--font-sans": t("--sans"),
    "--font-mono": t("--mono"),
    "--font-weight-normal": "400",
    "--font-weight-medium": "500",
    "--font-weight-semibold": "600",
    "--font-weight-bold": "700",
    "--border-radius-xs": "4px",
    "--border-radius-sm": "6px",
    "--border-radius-md": "10px",
    "--border-radius-lg": "14px",
    "--border-radius-xl": "18px",
    "--border-radius-full": "9999px",
    "--border-width-regular": "1px",
    "--shadow-hairline": `0 0 0 1px ${edge}`,
    "--shadow-sm": `0 1px 2px ${shadow}`,
    "--shadow-md": `0 4px 12px ${shadow}`,
    "--shadow-lg": `0 12px 32px ${shadow}`,
  };
  const text: [string, number, number][] = [["xs", 11, 16], ["sm", 12.5, 18], ["md", 14, 20], ["lg", 16, 24]];
  for (const [size, px, line] of text) {
    vars[`--font-text-${size}-size`] = `${px}px`;
    vars[`--font-text-${size}-line-height`] = `${line}px`;
  }
  const headings: [string, number, number][] = [
    ["xs", 13, 18], ["sm", 15, 20], ["md", 17, 24], ["lg", 20, 28], ["xl", 24, 32], ["2xl", 30, 36], ["3xl", 36, 44],
  ];
  for (const [size, px, line] of headings) {
    vars[`--font-heading-${size}-size`] = `${px}px`;
    vars[`--font-heading-${size}-line-height`] = `${line}px`;
  }
  return vars;
}

export interface HostContext {
  theme: "light" | "dark";
  variables: Record<string, string>;
  locale?: string;
  timeZone?: string;
  platform?: "web" | "desktop";
  hover?: boolean;
  touch?: boolean;
}

/** What the view asks of Zwans, beyond the bridge itself. Each may throw; the view gets the
 * message as a JSON-RPC error. */
export interface AppHost {
  callTool(name: string, args: Record<string, unknown>): Promise<unknown>;
  readResource(uri: string): Promise<unknown>;
  openLink(url: string): void;
  /** Text the view wants to say to the model, as the person. */
  message(text: string): void;
  resize(height: number): void;
}

interface JsonRpc {
  jsonrpc: "2.0";
  id?: string | number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;
const DENIED = -32000;

class RpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

/**
 * Zwans's end of one view's JSON-RPC. `post` sends a message to the view; `receive` takes
 * one from it. Until the view says it's initialized, Zwans sends it nothing unasked; then it
 * sends the tool's arguments and result, and later any change of theme.
 */
export class AppBridge {
  private initialized = false;
  private nextId = 1;
  private context: HostContext;

  constructor(
    private readonly view: AppView,
    private readonly host: AppHost,
    private readonly post: (message: JsonRpc) => void,
    context: HostContext,
    private readonly version = "",
  ) {
    this.context = context;
  }

  receive(data: unknown): void {
    const message = obj(data) as Partial<JsonRpc>;
    if (message.jsonrpc !== "2.0") return; // not ours: ignore it, as the spec says
    if (typeof message.method !== "string") return; // a reply to our teardown; nothing waits on it
    if (message.id === undefined) this.notification(message.method, obj(message.params));
    else void this.request(message.id, message.method, obj(message.params));
  }

  /** The theme changed: tell the view, once it's listening. */
  setContext(context: HostContext): void {
    const changed = context.theme !== this.context.theme || JSON.stringify(context.variables) !== JSON.stringify(this.context.variables);
    this.context = context;
    if (changed && this.initialized) {
      this.notify("ui/notifications/host-context-changed", { theme: context.theme, styles: { variables: context.variables } });
    }
  }

  /** The view is going away. It gets to know, but nothing waits for its answer. */
  teardown(reason: string): void {
    if (this.initialized) this.post({ jsonrpc: "2.0", id: `teardown-${this.nextId++}`, method: "ui/resource-teardown", params: { reason } });
  }

  private notification(method: string, params: Record<string, unknown>): void {
    switch (method) {
      case "ui/notifications/initialized":
        if (this.initialized) return;
        this.initialized = true;
        this.notify("ui/notifications/tool-input", { arguments: this.view.arguments });
        this.notify("ui/notifications/tool-result", this.view.result);
        break;
      case "ui/notifications/size-changed":
        if (typeof params.height === "number" && params.height > 0) this.host.resize(Math.min(Math.ceil(params.height), MAX_HEIGHT));
        break;
      case "notifications/message":
        console.info(`MCP view (${this.view.server}):`, params.data ?? params);
        break;
    }
  }

  private async request(id: string | number, method: string, params: Record<string, unknown>): Promise<void> {
    try {
      this.post({ jsonrpc: "2.0", id, result: await this.answer(method, params) });
    } catch (error) {
      const code = error instanceof RpcError ? error.code : DENIED;
      const text = error instanceof Error ? error.message : String(error);
      this.post({ jsonrpc: "2.0", id, error: { code, message: text } });
    }
  }

  private async answer(method: string, params: Record<string, unknown>): Promise<unknown> {
    switch (method) {
      case "ui/initialize":
        return this.initializeResult(params);
      case "ping":
        return {};
      case "tools/call":
        if (typeof params.name !== "string") throw new RpcError(INVALID_PARAMS, "tools/call needs a tool name");
        return this.host.callTool(params.name, obj(params.arguments));
      case "resources/read":
        if (typeof params.uri !== "string") throw new RpcError(INVALID_PARAMS, "resources/read needs a uri");
        return this.host.readResource(params.uri);
      case "ui/open-link": {
        const url = typeof params.url === "string" ? safeUrl(params.url) : null;
        if (!url) throw new RpcError(DENIED, "Invalid URL: only http and https links open");
        this.host.openLink(url);
        return {};
      }
      case "ui/message": {
        const text = messageText(params);
        if (text === null) throw new RpcError(INVALID_PARAMS, "Invalid message format: Zwans takes text");
        this.host.message(text);
        return {};
      }
      case "ui/request-display-mode":
        return { mode: "inline" }; // the only one Zwans has
      default:
        throw new RpcError(METHOD_NOT_FOUND, `Zwans doesn't support ${method}`);
    }
  }

  private initializeResult(params: Record<string, unknown>): Record<string, unknown> {
    const { theme, variables, locale, timeZone, platform, hover, touch } = this.context;
    const asked = typeof params.protocolVersion === "string" ? params.protocolVersion : PROTOCOL_VERSION;
    return {
      protocolVersion: asked <= PROTOCOL_VERSION ? asked : PROTOCOL_VERSION,
      hostInfo: { name: "zwans", version: this.version || "unknown" },
      hostCapabilities: {
        openLinks: {},
        serverTools: {},
        serverResources: {},
        logging: {},
        message: { text: {} },
        sandbox: {
          csp: this.view.csp,
          permissions: Object.fromEntries(allowed(this.view.permissions).map((p) => [p, {}])),
        },
      },
      hostContext: {
        toolInfo: { tool: this.view.tool },
        theme,
        styles: { variables },
        displayMode: "inline",
        availableDisplayModes: ["inline"],
        containerDimensions: { maxHeight: MAX_HEIGHT },
        ...(locale && { locale }),
        ...(timeZone && { timeZone }),
        ...(platform && { platform }),
        deviceCapabilities: { hover: hover ?? true, touch: touch ?? false },
      },
    };
  }

  private notify(method: string, params: unknown): void {
    this.post({ jsonrpc: "2.0", method, params });
  }
}

function safeUrl(text: string): string | null {
  try {
    const url = new URL(text);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/** The text of a ui/message: its content is one block or a list of them. */
function messageText(params: Record<string, unknown>): string | null {
  const blocks = Array.isArray(params.content) ? params.content : [params.content];
  const texts = blocks.map(obj).filter((block) => block.type === "text" && typeof block.text === "string");
  if (texts.length === 0) return null;
  return texts.map((block) => String(block.text)).join("\n\n");
}
