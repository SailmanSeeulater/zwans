/**
 * Lines up two transcripts of the same task, so a regression between two eval runs can be
 * traced to the step where the agent first did something different.
 *
 * Each transcript becomes a list of steps: a tool call (its name and key argument) or a
 * stretch of the model's text. The lists are matched with a longest common subsequence on
 * those signatures, which keeps the common steps side by side and shows each side's extra
 * steps against a gap.
 */

import { buildTurns, keyArgument, type RawEvent } from "./events";

export interface Step {
  kind: "call" | "text";
  label: string;
  signature: string; // what has to match for two steps to count as the same
  detail: string; // the result or the text, for a closer look
  isError: boolean;
}

export interface Row {
  a: Step | null;
  b: Step | null;
  same: boolean;
}

const DETAIL_CHARS = 2000;

// Each eval attempt works in its own temporary folder (zwans-eval-<task>-<random>/work, from
// the eval runner), so the same command in two runs differs only by that folder's name.
const ATTEMPT_FOLDER = /[^\s'"]*zwans-eval-[^\s'"/]+\/work/g;

/** A call's key argument with the attempt's folder taken out, so runs can be compared. */
export function normalize(text: string): string {
  return text.replace(ATTEMPT_FOLDER, ".").replace(/^cd \.\/? *&& */, "");
}

export function toSteps(events: RawEvent[]): Step[] {
  const steps: Step[] = [];
  for (const turn of buildTurns(events)) {
    for (const item of turn.items) {
      if (item.kind === "text" && item.text.trim()) {
        const text = item.text.trim();
        steps.push({
          kind: "text",
          label: text.split("\n")[0]?.slice(0, 120) ?? "",
          signature: "text",
          detail: text.slice(0, DETAIL_CHARS),
          isError: false,
        });
      } else if (item.kind === "tool") {
        const { call } = item;
        const key = normalize(keyArgument(call));
        steps.push({
          kind: "call",
          label: `${call.name} ${key}`.trim(),
          signature: `${call.name}\u0000${key}`,
          detail: (call.result?.content ?? "(no result)").slice(0, DETAIL_CHARS),
          isError: call.result?.isError ?? false,
        });
      }
    }
  }
  return steps;
}

export function align(a: Step[], b: Step[]): Row[] {
  // lengths[i][j]: the longest common subsequence of a[i:] and b[j:]
  const lengths = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lengths[i]![j] =
        a[i]!.signature === b[j]!.signature
          ? lengths[i + 1]![j + 1]! + 1
          : Math.max(lengths[i + 1]![j]!, lengths[i]![j + 1]!);
    }
  }
  const rows: Row[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    const left = a[i];
    const right = b[j];
    if (left && right && left.signature === right.signature) {
      const same = left.isError === right.isError && (left.kind === "call" || left.detail === right.detail);
      rows.push({ a: left, b: right, same });
      i++;
      j++;
    } else if (right && (!left || lengths[i]![j + 1]! >= lengths[i + 1]![j]!)) {
      rows.push({ a: null, b: right, same: false });
      j++;
    } else if (left) {
      rows.push({ a: left, b: null, same: false });
      i++;
    }
  }
  return rows;
}

/** The first row where the two runs part ways, or -1 if they never do. */
export function firstDivergence(rows: Row[]): number {
  return rows.findIndex((row) => !row.same);
}
