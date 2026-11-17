/** Finds eval runs that answer a question the inspector raises, such as "what did the cache save?". */

import type { RunListing } from "./api";

/** The latest pair of runs of the same tasks and model, with configs `a` and `b`. */
export function findPair(runs: RunListing[], a: string, b: string): [RunListing, RunListing] | null {
  const key = (r: RunListing) => `${r.model}|${[...r.tasks].sort().join(",")}`;
  for (const second of [...runs].reverse()) {
    if (second.config !== b) continue;
    const first = [...runs].reverse().find((r) => r.config === a && key(r) === key(second));
    if (first) return [first, second];
  }
  return null;
}

export const compareLink = (a: string, b: string) =>
  `/evals/compare/?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
