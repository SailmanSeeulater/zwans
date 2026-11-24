/** What a working session is doing right now, in a few words, for the line under the
 * conversation, the sidebar's dot and the browser tab. */
import { keyArgument, type RawEvent, type ToolCall, type Turn } from "./events";

export interface Phase {
  verb: string;
  /** What it's being done to: a path, a command, a pattern. */
  detail: string;
}

const VERBS: Record<string, string> = {
  Read: "Reading",
  Outline: "Reading",
  Docs: "Reading the docs",
  Grep: "Searching",
  Glob: "Looking for files",
  References: "Finding references",
  Edit: "Editing",
  MultiEdit: "Editing",
  Write: "Writing",
  Rename: "Renaming",
  Bash: "Running",
  BashOutput: "Checking on",
  KillBash: "Stopping",
  Python: "Running Python",
  RunTests: "Running the tests",
  Diagnostics: "Checking for problems",
  ShowChanges: "Reviewing the changes",
  Task: "Handing off",
  TodoWrite: "Planning",
  Memory: "Remembering",
  Skill: "Using a skill",
  WebFetch: "Fetching",
  Video: "Watching",
  NotebookEdit: "Editing the notebook",
  Logs: "Reading the log",
  Database: "Querying",
  Packages: "Looking up",
  Http: "Requesting",
  Browser: "Using the page",
  Profile: "Profiling",
  WebSearch: "Searching the web",
  AskUser: "Asking you",
};

const THINKING: Phase = { verb: "Thinking", detail: "" };

function ofCall(call: ToolCall): Phase {
  if (call.permission?.state === "asking") return { verb: "Waiting for you", detail: "" };
  // A subagent's latest unfinished call says more than "Handing off".
  const inner = call.subcalls.findLast((sub) => !sub.result);
  if (inner) return ofCall(inner);
  return { verb: VERBS[call.name] ?? `Using ${call.name}`, detail: keyArgument(call) };
}

/** The phase a running turn is in, from the last thing in it: a call still running names
 * itself, text still arriving is "Writing", and anything finished means the model is
 * thinking about what comes next. */
export function phaseOf(turns: Turn[]): Phase {
  const last = turns.at(-1)?.items.at(-1);
  if (!last) return THINKING;
  if (last.kind === "tool") return last.call.result ? THINKING : ofCall(last.call);
  if (last.kind === "text") return { verb: "Writing", detail: "" };
  return THINKING;
}

/** When the turn that's running began, in ms, or null when the events carry no times. */
export function turnStartedAt(events: RawEvent[]): number | null {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (event?.type !== "turn_started") continue;
    const at = event.time ? Date.parse(event.time) : NaN;
    return Number.isNaN(at) ? null : at;
  }
  return null;
}

/** 7 → "7s", 65 → "1m 05s", 3700 → "1h 01m". */
export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export type Liveness = "working" | "waiting" | "idle";

export function livenessOf(status: { running: boolean; waiting_for: string[] } | null | undefined): Liveness {
  if (!status?.running) return "idle";
  return status.waiting_for.length ? "waiting" : "working";
}

/** The browser tab's title: a mark while it works, a count while it waits for an answer. */
export function tabTitle(title: string, liveness: Liveness, waiting: number): string {
  const name = title ? `${title} · Zwans` : "Zwans";
  if (liveness === "waiting") return `(${Math.max(1, waiting)}) ${name}`;
  return liveness === "working" ? `◌ ${name}` : name;
}
