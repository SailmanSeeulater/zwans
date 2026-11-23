/**
 * Races: one task given to two models at once, each in its own copy of the project. These
 * helpers say where each side stands and how the race's money splits between them.
 */
import type { RawEvent } from "./events";

export const LETTERS = ["A", "B"] as const;

export type LaneState = "working" | "waiting" | "done" | "budget" | "stopped" | "error" | "starting";

/** Where one side of a race stands, from its session's status and events. */
export function laneState(running: boolean, waiting: boolean, events: RawEvent[]): LaneState {
  if (waiting) return "waiting";
  if (running) return "working";
  const ended = [...events].reverse().find((event) => event.type === "turn_ended");
  if (!ended) return "starting";
  switch (ended.stop_reason) {
    case "budget":
      return "budget";
    case "interrupted":
      return "stopped";
    case "error":
    case "refusal":
      return "error";
    default:
      return "done";
  }
}

export const STATE_LABELS: Record<LaneState, string> = {
  working: "Working",
  waiting: "Waiting for you",
  done: "Done",
  budget: "Out of budget",
  stopped: "Stopped",
  error: "Hit an error",
  starting: "Starting",
};

/** Each side's share of the bar under a race: of its budget when it has one, else of what
 * both have spent, so the two segments always fit. */
export function shares(spent: number[], budget: number | null | undefined): number[] {
  const total = spent.reduce((sum, n) => sum + n, 0);
  const whole = budget && budget > 0 ? Math.max(budget, total) : total;
  if (whole <= 0) return spent.map(() => 0);
  return spent.map((n) => n / whole);
}

/** "$0.50" → 0.5; "", "off" and "none" → null; anything else → NaN, to be refused. */
export function readBudget(text: string): number | null {
  const trimmed = text.trim().replace(/^\$/, "");
  if (!trimmed || /^(off|none)$/i.test(trimmed)) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : NaN;
}
