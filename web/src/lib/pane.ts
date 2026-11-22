/**
 * The pane beside a session's conversation: its tabs, how wide it is and whether it shows.
 * The first tab is always "Under the hood"; the others are pages opened to look at beside
 * the conversation, such as the dev server of the project being worked on. All of it is
 * kept in localStorage, so the pane comes back as it was left.
 */

export interface PageTab {
  id: string;
  url: string; // "" for a tab with nothing opened yet
}

export interface PaneState {
  open: boolean;
  width: number; // pixels
  pages: PageTab[];
  active: string; // HOOD, or a page tab's id
}

export const HOOD = "hood";
export const DEFAULT_WIDTH = 320;
export const MIN_WIDTH = 280;
export const MIN_MAIN = 420; // what the conversation keeps, however far the pane is dragged
export const MAX_PAGES = 8;
const KEY = "zwans-pane";

export const DEFAULT_PANE: PaneState = { open: true, width: DEFAULT_WIDTH, pages: [], active: HOOD };

/** The width nearest `wanted` that leaves the conversation room in a session `total` wide. */
export function clampWidth(wanted: number, total: number): number {
  const most = Math.max(MIN_WIDTH, total - MIN_MAIN);
  return Math.round(Math.min(Math.max(wanted, MIN_WIDTH), most));
}

/**
 * What someone typed in the address box as a URL to load, or null when it isn't one.
 * "localhost:3000" and "127.0.0.1:8000/docs" get http, since that's what a dev server
 * speaks; anything else without a scheme gets https. Only http and https load.
 */
export function toUrl(typed: string): string | null {
  const text = typed.trim();
  if (!text || /\s/.test(text)) return null;
  const local = /^(localhost|127\.0\.0\.1|\[::1\]|[^/:]+\.localhost)(:\d+)?(\/|$)/i.test(text);
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `${local ? "http" : "https"}://${text}`;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (!url.hostname.includes(".") && url.hostname !== "localhost" && !url.hostname.startsWith("[")) return null;
    return url.href;
  } catch {
    return null;
  }
}

/** A tab's label: the page's host, and its path when that says more. */
export function tabLabel(url: string): string {
  if (!url) return "New tab";
  try {
    const { host, pathname } = new URL(url);
    return pathname.length > 1 ? `${host}${pathname}` : host;
  } catch {
    return url;
  }
}

/** A saved state made safe to use: whatever is missing or malformed falls back to the default. */
export function restore(saved: unknown): PaneState {
  if (typeof saved !== "object" || saved === null) return DEFAULT_PANE;
  const from = saved as Record<string, unknown>;
  const pages = (Array.isArray(from.pages) ? from.pages : [])
    .filter((p): p is PageTab => typeof p?.id === "string" && typeof p?.url === "string")
    .filter((p) => p.url === "" || toUrl(p.url) !== null)
    .slice(0, MAX_PAGES);
  const width = typeof from.width === "number" && Number.isFinite(from.width) ? from.width : DEFAULT_WIDTH;
  const active = pages.some((p) => p.id === from.active) ? String(from.active) : HOOD;
  return { open: from.open !== false, width: Math.max(MIN_WIDTH, Math.round(width)), pages, active };
}

export function readPane(): PaneState {
  try {
    return restore(JSON.parse(localStorage.getItem(KEY) ?? "null"));
  } catch {
    return DEFAULT_PANE;
  }
}

export function savePane(state: PaneState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Private windows and full storage: the pane still works, it just isn't remembered.
  }
}

/** The state with a new empty tab, showing; unchanged once MAX_PAGES are open. */
export function withNewPage(state: PaneState, id: string): PaneState {
  if (state.pages.length >= MAX_PAGES) return state;
  return { ...state, open: true, pages: [...state.pages, { id, url: "" }], active: id };
}

/** The state without a tab. Closing the one showing shows its neighbour. */
export function withoutPage(state: PaneState, id: string): PaneState {
  const at = state.pages.findIndex((p) => p.id === id);
  if (at < 0) return state;
  const pages = state.pages.filter((p) => p.id !== id);
  const active = state.active !== id ? state.active : (pages[at] ?? pages[at - 1])?.id ?? HOOD;
  return { ...state, pages, active };
}
