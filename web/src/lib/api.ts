/**
 * Talking to `zwans serve`: the token, HTTP calls, and a session's WebSocket.
 *
 * The server prints a link with the token after `#`, which browsers never send to a
 * server. The first page that sees it keeps it in localStorage and takes it out of the
 * address bar.
 */

const TOKEN_KEY = "zwans-token";

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

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(API_BASE + path, {
    ...init,
    headers: {
      Authorization: `Bearer ${readToken() ?? ""}`,
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
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
  const base = API_BASE || window.location.origin;
  const url = base.replace(/^http/, "ws") + `/api/sessions/${encodeURIComponent(id)}/events`;
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
}

export interface SavedSession {
  id: string;
  title: string;
  workspace: string;
  model: string;
  turns: number;
  updated_at: string;
  dollars: number;
  live: boolean;
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
