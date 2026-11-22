/**
 * Talking to `zwans serve`: the token, HTTP calls, and a session's WebSocket.
 *
 * The server prints a link with the token after `#`, which browsers never send to a
 * server. The first page that sees it keeps it in localStorage and takes it out of the
 * address bar.
 */

const TOKEN_KEY = "zwans-token";
/** Sent on `window` when the stored token changes, so pages check again whether they have one. */
export const TOKEN_EVENT = "zwans:token";

declare global {
  interface Window {
    /** Set only inside the desktop app (desktop/preload.cjs). */
    zwansDesktop?: { pickFolder(): Promise<string | null> };
  }
}

/** Where the API is: the page's own server, or a separate one while developing with
 * `next dev` (set NEXT_PUBLIC_ZWANS_API=http://localhost:8765). */
export const API_BASE = process.env.NEXT_PUBLIC_ZWANS_API ?? "";

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  const fromLink = new URLSearchParams(window.location.hash.slice(1)).get("token");
  if (fromLink) {
    try {
      localStorage.setItem(TOKEN_KEY, fromLink);
    } catch {
      // Private windows can refuse storage; the token still works for this page.
    }
    history.replaceState(null, "", window.location.pathname + window.location.search);
    return fromLink;
  }
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Forget a token the server refused: it makes a new one each time it starts. Pages then
 * ask for the link again instead of showing nothing. */
function forgetToken(refused: string | null) {
  try {
    if (refused && localStorage.getItem(TOKEN_KEY) === refused) localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage is blocked, so there was nothing kept to forget.
  }
  window.dispatchEvent(new Event(TOKEN_EVENT));
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = readToken();
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: {
      Authorization: `Bearer ${token ?? ""}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (response.status === 401) forgetToken(token);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body) detail = String(body.detail);
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** A session's event stream. The token goes in the first message, as the server expects. */
export function sessionSocket(id: string): WebSocket {
  return socketTo(`/api/sessions/${encodeURIComponent(id)}/events`);
}

/** A room's event stream, authenticated the same way. */
export function roomSocket(id: string): WebSocket {
  return socketTo(`/api/rooms/${encodeURIComponent(id)}/events`);
}

function socketTo(path: string): WebSocket {
  const base = API_BASE || window.location.origin;
  const url = base.replace(/^http/, "ws") + path;
  const ws = new WebSocket(url);
  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ type: "auth", token: readToken() ?? "" }));
  });
  return ws;
}

// -- what the server sends

export type Mode = "read-only" | "ask" | "auto";

export interface SessionStatus {
  type: "status";
  id: string;
  title: string;
  pinned?: boolean;
  workspace: string;
  model: string;
  mode: Mode;
  executor: string;
  running: boolean;
  turns: number;
  dollars: number;
  context_tokens: number;
  waiting_for: string[];
  warnings: string[];
  /** The session's spending cap in dollars; null for none. */
  budget?: number | null;
  /** The model runs on this machine. */
  local?: boolean;
  /** Who a stuck local session can hand its task to; null when no one. */
  handoff_model?: string | null;
  /** What was sent during the running turn that the model hasn't read yet. */
  queued?: string[];
  /** The scripted replay: no API calls. */
  demo?: boolean;
  /** A conversation with no project folder and none of Zwans's tools. */
  chat?: boolean;
  /** Estimated context tokens that trigger a compaction. */
  compact_at?: number;
}

export interface DemoInfo {
  /** What each of the demo's turns is scripted for. */
  prompts: string[];
  note: string;
  /** Whether the server has a credential set. It may still be refused. */
  has_credential: boolean;
  /** Why the configured model can't be used yet, in the server's words; null when it can. */
  credential_problem: string | null;
  /** The model a new session or chat starts with unless another is chosen. */
  model: string;
}

/** The last request a session sent, exactly as the API got it (never the credential). */
export interface LastRequest {
  request: Record<string, unknown> | null;
}

/** Keeps a session's first task, for its page to send once it has connected. */
export function rememberFirstPrompt(id: string, prompt: string) {
  try {
    sessionStorage.setItem(`zwans-first-prompt:${id}`, prompt);
  } catch {
    // storage refused: the user types it instead
  }
}

export function takeFirstPrompt(id: string): string | null {
  try {
    const key = `zwans-first-prompt:${id}`;
    const prompt = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    return prompt;
  } catch {
    return null;
  }
}

/** A file a turn changed, as checkpoints see it. */
export interface FileChange {
  status: "added" | "changed" | "deleted";
  path: string;
}

/** A turn that can be undone, with the files it changed. */
export interface UndoableTurn {
  turn: number;
  prompt: string;
  changes: FileChange[];
}

/** Everything a session has changed since its first checkpoint, for the Changes panel. */
export interface SessionChanges {
  changes: FileChange[];
  /** A unified diff of them, cut short when `cut`. */
  diff: string;
  cut: boolean;
  /** Why this session has no changes to show (the demo, a chat, checkpoints off), when it hasn't. */
  problem: string | null;
}

export interface UndoableTurns {
  /** Newest first. */
  turns: UndoableTurn[];
  /** Why turns can't be undone in this session at all, when they can't. */
  problem: string | null;
}

/** What undoing a turn did. The session is reopened, so its socket has to reconnect. */
export interface RewindResult {
  status: SessionStatus;
  /** The undoing's changes: a "deleted" file was new in the undone turns. */
  undone: FileChange[];
  /** The undone turn's prompt, to edit and send again. */
  draft: string;
}

/** What one provider offers: GET /api/models. */
export interface ModelListing {
  provider: string;
  about: string;
  /** Full names, as the session takes them. */
  models: string[];
  /** Whether its models can be used now, as far as the server can tell. */
  ready: boolean;
  /** Why it isn't ready, or how to see more. */
  note: string;
  local: boolean;
}

/** An image to send with a prompt: base64 data, checked again by the server. */
export interface PromptImage {
  name: string;
  data: string;
}

export interface SavedSession {
  id: string;
  title: string; // the person's name for it, or else from its first prompt
  named: boolean; // whether the title is a name the person gave
  pinned: boolean;
  workspace: string;
  model: string;
  turns: number;
  updated_at: string;
  dollars: number;
  live: boolean;
  chat?: boolean;
}

export interface SessionList {
  live: SessionStatus[];
  saved: SavedSession[];
}

export interface Summary {
  attempts: number;
  passed: number;
  pass_rate: number;
  dollars: number;
  mean_dollars: number;
  mean_model_calls: number;
  mean_tool_calls: number;
  tool_error_rate: number;
  mean_seconds: number;
  planted_attempts?: number;
  planted_runs?: number;
}

export interface RunListing {
  name: string;
  agent: string;
  executor: string;
  config: string;
  model: string;
  effort: string;
  started_at: string;
  repeats: number;
  tasks: string[];
  summary: Summary;
}

/** One thing that was run on a set of tasks, with its runs pooled. */
export interface LeaderRow {
  agent: string;
  model: string;
  effort: string;
  executor: string;
  config: string;
  runs: string[]; // oldest first
  attempts: number;
  passed: number;
  pass_rate: number;
  /** The 95% interval for the pass rate, from the number of attempts. */
  low: number;
  high: number;
  mean_dollars: number;
  mean_seconds: number;
  mean_model_calls: number;
  /** Against the best row, task by task: level means the tasks can't tell them apart. */
  standing: "best" | "level" | "behind" | "too_few_tasks";
  /** No other row passes at least as often for no more money. */
  frontier: boolean;
}

export interface Leaderboard {
  tasks: string[];
  runs: number;
  rows: LeaderRow[]; // best first
}

export interface Attempt {
  task: string;
  category: string;
  repeat: number;
  status: "passed" | "failed" | "stopped";
  stop_reason: string;
  dollars: number;
  model_calls: number;
  tool_calls: number;
  tool_errors: number;
  seconds: number;
  check_exit: number | null;
  check_output: string;
  errors: string[];
  transcript: string; // a file name in the run's transcripts folder
  planted_attempts: string[];
  planted_runs: string[];
}

export interface Report {
  agent: string;
  executor: string;
  config: { name: string; settings: Record<string, unknown> };
  model: string;
  effort: string;
  started_at: string;
  repeats: number;
  budget: number | null;
  out_of_budget: boolean;
  summary: Summary;
  tasks: Record<string, Summary>;
  attempts: Attempt[];
}

export interface Difference {
  metric: string;
  a: number;
  b: number;
  delta: number;
  low: number;
  high: number;
  significant: boolean;
}

export interface Comparison {
  a: string;
  b: string;
  tasks: string[];
  only_in_a: string[];
  only_in_b: string[];
  differences: Difference[];
  task_pass_rates: Record<string, [number, number]>;
}

// -- rooms: several agents, each on its own model, talking to each other

export interface RoomAgent {
  name: string;
  model: string;
  /** Who they are in the room, as "a skeptical security reviewer". */
  persona: string;
}

export interface RoomLine {
  /** An agent's name, or "User" for the person. */
  speaker: string;
  text: string;
  /** The model that wrote it; empty for the user. */
  model: string;
  /** Null when the model's price isn't known. */
  dollars: number | null;
  /** Stopped partway through. */
  cut: boolean;
}

/** The whole room, as the server sends it on connecting and after every run. */
export interface RoomStatus {
  type: "room";
  id: string;
  topic: string;
  agents: RoomAgent[];
  lines: RoomLine[];
  dollars: number;
  unpriced: string[];
  budget: number | null;
  created_at: string;
  updated_at: string;
  running: boolean;
  /** The reply being written, when one is. */
  speaking: { speaker: string; model: string; text: string } | null;
  /** Who speaks next unless someone is mentioned. */
  next: string;
}

export type RoomMessage =
  | RoomStatus
  | { type: "speaker_started"; speaker: string; model: string }
  | { type: "speaker_text"; speaker: string; text: string }
  | { type: "line_added"; line: RoomLine; dollars: number }
  | { type: "room_stopped"; reason: "turns" | "budget" | "stopped" | "error"; detail: string }
  | { type: "server_error"; message: string };

export interface SavedRoom {
  id: string;
  topic: string;
  agents: RoomAgent[];
  lines: number;
  dollars: number;
  updated_at: string;
  live: boolean;
  running: boolean;
}
