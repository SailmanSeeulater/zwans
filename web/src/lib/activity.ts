/**
 * Small pictures of a session: the activity strip beside the conversation, the size of each
 * edit, and how full the context is.
 */
import type { ToolCall, Turn } from "./events";

export type Kind = "read" | "edit" | "run" | "other";
/** How a call came out: tests passed or failed, or it failed in some other way. */
export type Outcome = "passed" | "failed" | "error" | null;

export interface Mark {
  id: string;
  turn: number; // the turn's place in the list, from 0
  kind: Kind;
  outcome: Outcome;
  label: string;
}

const EDITS = new Set(["Edit", "MultiEdit", "Write", "Rename"]);
const RUNS = new Set(["Bash", "BashOutput", "Python", "RunTests", "Diagnostics", "Task"]);
const READS = new Set(["Read", "Grep", "Glob", "Outline", "References", "Docs", "ShowChanges", "WebFetch", "WebSearch", "Memory", "Skill", "Video"]);

export function kindOf(name: string): Kind {
  if (EDITS.has(name)) return "edit";
  if (RUNS.has(name)) return "run";
  if (READS.has(name)) return "read";
  return "other";
}

// A command that runs a project's tests, by the usual runners' names.
const TEST_COMMAND =
  /\b(pytest|unittest|vitest|jest|rspec|phpunit|tox|(npm|pnpm|yarn|bun)( run)? test|(go|cargo|mvn|gradle|make|dotnet|mix|swift) test)\b/;

/** How a call came out. RunTests says how the tests went in its first line, and a Bash
 * command that runs tests by its exit code; tests failing isn't the call failing. */
export function outcomeOf(call: Pick<ToolCall, "name" | "args" | "result">): Outcome {
  if (!call.result) return null;
  const { content, isError } = call.result;
  if (call.name === "RunTests") {
    if (content.startsWith("Tests failed")) return "failed";
    if (content.startsWith("All tests passed")) return "passed";
  }
  if (call.name === "Bash" && !isError && TEST_COMMAND.test(String(call.args.command ?? ""))) {
    const exit = /\(exit code (-?\d+)\)\s*$/.exec(content);
    if (exit) return exit[1] === "0" ? "passed" : "failed";
  }
  return isError ? "error" : null;
}

const OUTCOME_WORDS: Record<Exclude<Outcome, null>, string> = {
  passed: "tests passed",
  failed: "tests failed",
  error: "failed",
};

/** One mark per tool call the model made, in order. A subagent's calls stay inside its Task. */
export function activity(turns: Turn[], describe: (call: ToolCall) => string = () => ""): Mark[] {
  const marks: Mark[] = [];
  turns.forEach((turn, index) => {
    for (const item of turn.items) {
      if (item.kind !== "tool" || item.call.name === "TodoWrite" || item.call.name === "AskUser") continue;
      const { call } = item;
      const outcome = outcomeOf(call);
      const about = describe(call);
      const label = [call.name, about, outcome ? `(${OUTCOME_WORDS[outcome]})` : ""].filter(Boolean).join(" ");
      marks.push({ id: call.id, turn: index, kind: kindOf(call.name), outcome, label });
    }
  });
  return marks;
}

/** Lines a unified diff adds and removes, leaving out its file headers. */
export function diffStat(diff: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+") && !line.startsWith("+++")) added += 1;
    else if (line.startsWith("-") && !line.startsWith("---")) removed += 1;
  }
  return { added, removed };
}

/** GitHub's five blocks: added and removed in proportion, any change getting at least one,
 * and the rest empty when the change is small. */
export function diffBlocks(added: number, removed: number, blocks = 5): ("add" | "del" | "none")[] {
  const total = added + removed;
  if (total === 0) return Array(blocks).fill("none");
  const filled = Math.min(blocks, total);
  let add = Math.round((added / total) * filled);
  if (added > 0 && add === 0) add = 1;
  if (removed > 0 && add === filled) add = filled - 1;
  return [...Array(add).fill("add"), ...Array(filled - add).fill("del"), ...Array(blocks - filled).fill("none")];
}

/** How full the context is, as a share of where compaction starts. */
export function contextShare(tokens: number, compactAt: number): number {
  if (!(compactAt > 0) || !(tokens > 0)) return 0;
  return Math.min(1, tokens / compactAt);
}

/** 1234 as "1.2k", 160000 as "160k". */
export function shortTokens(tokens: number): string {
  if (tokens < 1000) return String(Math.round(tokens));
  if (tokens < 10_000) return `${(tokens / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (tokens < 1_000_000) return `${Math.round(tokens / 1000)}k`;
  return `${(tokens / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}
