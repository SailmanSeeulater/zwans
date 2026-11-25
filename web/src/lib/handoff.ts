/**
 * Local first, Claude when stuck: a session on a model running on this machine works for
 * free, and when a turn of it gets stuck the page offers to hand the task to a stronger
 * model, which carries on with the whole conversation so far.
 */
import { outcomeOf } from "./activity";
import type { ToolCall, Turn } from "./events";

const FAILED_CALLS = 3; // this many failed calls in a turn reads as stuck

/** Why a finished turn looks stuck, said so it follows "It ", or null when it doesn't. */
export function stuckReason(turn: Turn | undefined): string | null {
  if (!turn?.stop) return null;
  const { reason } = turn.stop;
  if (reason === "interrupted" || reason === "refusal") return null; // the person's call, or a choice
  if (reason === "max_steps") return "ran out of steps before finishing";
  if (reason === "repeating") return "kept repeating the same tool calls";
  if (reason === "max_tokens") return "ran out of room in its reply";
  if (reason === "error") return "stopped on an error";

  const calls: ToolCall[] = [];
  for (const item of turn.items) if (item.kind === "tool") calls.push(item.call);
  const outcomes = calls.map(outcomeOf);
  const lastTests = [...outcomes].reverse().find((o) => o === "passed" || o === "failed");
  if (lastTests === "failed") return "finished with the tests still failing";
  const failed = outcomes.filter((o) => o === "error").length;
  if (failed >= FAILED_CALLS) return `had ${failed} tool calls fail`;
  return null;
}

/** What the new model is asked, so it knows it's picking up someone else's work. */
export function handoffPrompt(from: string, reason: string): string {
  return (
    `You're taking over this task from ${from}, which ${reason}. ` +
    "Look at what it did and what's left, finish the task, and check that it works."
  );
}

/** "Claude Sonnet 5.5" from "claude-sonnet-5-5"; other names as they are. */
export function modelName(model: string): string {
  const claude = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(model);
  if (!claude) return model.split("/").at(-1) ?? model;
  const [, family = "", major, minor] = claude;
  return `Claude ${family.charAt(0).toUpperCase()}${family.slice(1)} ${major}.${minor}`;
}
