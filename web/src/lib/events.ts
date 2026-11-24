/**
 * Turns Zwans's event stream (src/zwans/events.py) into a conversation to show: turns, each
 * with the model's text, its tool calls and their results, and what the user was asked.
 * The live session view and the eval transcript view both use it.
 */

import { parseApp, type AppView } from "./apps";

export interface RawEvent {
  type: string;
  time?: string;
  [key: string]: unknown;
}

export type PermissionState = "asking" | "allowed" | "declined" | "denied";

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  /** Set for a call an MCP app's view made, which the model never saw. */
  byView?: boolean;
  /** From the request to the result, when the events carry times. */
  seconds?: number;
  result?: { content: string; isError: boolean; untrusted: boolean; diff: string | null; app?: AppView };
  /** `rules` is what "always allow" would add; `preview` the diff an Edit or Write would make. */
  permission?: { state: PermissionState; reason: string; rules: string[]; preview: string | null };
  hooks: { event: string; message: string }[];
  /** For a Task call: what its subagent did. */
  subcalls: ToolCall[];
}

export type Item =
  | { kind: "text"; text: string }
  | { kind: "note"; text: string }
  /** Something the user sent while the turn ran, which the model read at its next step. */
  | { kind: "steer"; text: string }
  /** /loop ran its check: before the first turn (round 0) and after each. */
  | { kind: "loop-check"; check: string; round: number; rounds: number; passed: boolean; exitCode: number | null; output: string }
  | { kind: "loop-end"; reason: string; detail: string }
  | { kind: "tool"; call: ToolCall }
  | { kind: "error"; message: string }
  | { kind: "compacted"; before: number; after: number; summary: string }
  | { kind: "hook"; event: string; message: string };

export interface Turn {
  prompt: string;
  /** The session's number for this turn; 0 in transcripts from before it was recorded. */
  number: number;
  /** How many images were sent with the prompt. */
  images: number;
  items: Item[];
  stop?: { reason: string; detail: string };
  modelCalls: number;
  inputTokens: number;
  outputTokens: number;
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" ? value : 0);
const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

export function buildTurns(events: RawEvent[]): Turn[] {
  const turns: Turn[] = [];
  const calls = new Map<string, ToolCall>(); // every call so far, by id, subagents' included
  const tasks = new Map<string, ToolCall>(); // running Task calls, by their description
  const started = new Map<string, number>(); // when each call was requested, in ms

  const current = (): Turn => {
    let turn = turns.at(-1);
    if (!turn) {
      turn = { prompt: "", number: 0, images: 0, items: [], modelCalls: 0, inputTokens: 0, outputTokens: 0 };
      turns.push(turn);
    }
    return turn;
  };

  const appendText = (items: Item[], kind: "text" | "note", text: string) => {
    const last = items.at(-1);
    if (last && last.kind === kind) last.text += text;
    else items.push({ kind, text });
  };

  const apply = (event: RawEvent, items: Item[] | null, parent: ToolCall | null) => {
    switch (event.type) {
      case "turn_started":
        if (!parent) {
          turns.push({
            prompt: str(event.prompt),
            number: num(event.turn),
            images: num(event.images),
            items: [],
            modelCalls: 0,
            inputTokens: 0,
            outputTokens: 0,
          });
        }
        break;
      case "text_delta":
        if (items) appendText(items, "text", str(event.text));
        break;
      case "thinking_delta":
        if (items) appendText(items, "note", str(event.text));
        break;
      case "tool_call_requested": {
        const call: ToolCall = {
          id: str(event.call_id),
          name: str(event.name),
          args: obj(event.args),
          ...(event.by === "view" && { byView: true }),
          hooks: [],
          subcalls: [],
        };
        if (event.time) started.set(call.id, Date.parse(str(event.time)));
        calls.set(call.id, call);
        if (parent) parent.subcalls.push(call);
        else if (items) items.push({ kind: "tool", call });
        if (call.name === "Task") tasks.set(str(call.args.description), call);
        break;
      }
      case "permission_requested": {
        const call = calls.get(str(event.call_id));
        if (call) {
          const rules = Array.isArray(event.rules) ? event.rules.map(String) : [];
          const preview = typeof event.preview === "string" ? event.preview : null;
          call.permission = { state: "asking", reason: str(event.reason), rules, preview };
        }
        break;
      }
      case "permission_resolved": {
        const call = calls.get(str(event.call_id));
        if (call?.permission) call.permission.state = event.allowed ? "allowed" : "declined";
        // Time the call from the answer, so the wait for it isn't counted as the tool's.
        if (call && event.time) started.set(call.id, Date.parse(str(event.time)));
        break;
      }
      case "permission_denied": {
        const call = calls.get(str(event.call_id));
        if (call) call.permission = { state: "denied", reason: str(event.reason), rules: [], preview: null };
        break;
      }
      case "tool_result": {
        const call = calls.get(str(event.call_id));
        const app = event.app ? parseApp(event.app) : null;
        if (call) {
          call.result = {
            content: str(event.content),
            isError: Boolean(event.is_error),
            untrusted: Boolean(event.untrusted),
            diff: typeof event.diff === "string" ? event.diff : null,
            ...(app && { app }),
          };
          const start = started.get(call.id);
          if (start !== undefined && event.time) call.seconds = (Date.parse(str(event.time)) - start) / 1000;
        }
        break;
      }
      case "hook_reported": {
        const call = calls.get(str(event.call_id));
        const hook = { event: str(event.event), message: str(event.message) };
        if (call) call.hooks.push(hook);
        else if (items) items.push({ kind: "hook", ...hook });
        break;
      }
      case "subagent": {
        const task = tasks.get(str(event.task));
        apply(obj(event.event) as RawEvent, null, task ?? null);
        break;
      }
      case "usage_updated": {
        if (event.purpose === "title") break; // naming the session, not part of the turn
        const turn = current();
        turn.modelCalls += 1;
        turn.inputTokens +=
          num(event.input_tokens) + num(event.cache_read_tokens) + num(event.cache_write_tokens);
        turn.outputTokens += num(event.output_tokens);
        break;
      }
      case "context_compacted":
        if (items) {
          items.push({
            kind: "compacted",
            before: num(event.tokens_before),
            after: num(event.tokens_after),
            summary: str(event.summary),
          });
        }
        break;
      case "loop_checked":
        if (items) {
          items.push({
            kind: "loop-check",
            check: str(event.check),
            round: num(event.round),
            rounds: num(event.rounds),
            passed: Boolean(event.passed),
            exitCode: typeof event.exit_code === "number" ? event.exit_code : null,
            output: str(event.output),
          });
        }
        break;
      case "loop_ended":
        if (items) items.push({ kind: "loop-end", reason: str(event.reason), detail: str(event.detail) });
        break;
      case "steered":
        if (items) items.push({ kind: "steer", text: str(event.text) });
        break;
      case "turn_ended":
        if (!parent) current().stop = { reason: str(event.stop_reason), detail: str(event.detail) };
        break;
      case "error":
        if (items) items.push({ kind: "error", message: str(event.message) });
        else if (parent) parent.hooks.push({ event: "error", message: str(event.message) });
        break;
    }
  };

  for (const event of events) {
    const turn = event.type === "turn_started" ? null : current();
    apply(event, turn ? turn.items : null, null);
  }
  return turns;
}

/** The calls still waiting for the user's answer, oldest first. */
export function waitingCalls(turns: Turn[]): ToolCall[] {
  const waiting: ToolCall[] = [];
  const visit = (call: ToolCall) => {
    if (call.permission?.state === "asking") waiting.push(call);
    call.subcalls.forEach(visit);
  };
  for (const turn of turns) {
    for (const item of turn.items) if (item.kind === "tool") visit(item.call);
  }
  return waiting;
}

/** The model's question that nobody has answered yet: an AskUser call with no result. */
export function pendingQuestion(turns: Turn[]): { question: string; options: string[] } | null {
  const last = turns.at(-1);
  if (!last || last.stop) return null;
  for (const item of last.items) {
    if (item.kind !== "tool" || item.call.name !== "AskUser" || item.call.result) continue;
    const { question, options } = item.call.args;
    return {
      question: typeof question === "string" ? question : "",
      options: Array.isArray(options) ? options.map(String).filter(Boolean) : [],
    };
  }
  return null;
}

/** The one argument worth showing for a call, so it fits on a line. */
export function keyArgument(call: Pick<ToolCall, "name" | "args">): string {
  const { edits, paths } = call.args;
  if (call.name === "MultiEdit" && Array.isArray(edits)) {
    const files = [...new Set(edits.map((e: unknown) => String((e as { path?: unknown } | null)?.path ?? "")))];
    return `${edits.length} ${edits.length === 1 ? "edit" : "edits"} in ${files.join(", ")}`;
  }
  if (call.name === "Diagnostics" || call.name === "RunTests") {
    const named = Array.isArray(paths) && paths.length ? paths.map(String).join(" ") : "the whole project";
    return call.args.filter ? `${named} matching ${String(call.args.filter)}` : named;
  }
  if (call.name === "Rename") return `${String(call.args.old ?? "")} to ${String(call.args.new ?? "")}`;
  const keys = ["command", "pattern", "symbol", "path", "query", "url", "question", "description", "name", "job_id", "ticket", "code", "target", "ref", "action", "text", "test", "container", "expression", "source", "message", "run", "branch", "before", "title"];
  for (const key of keys) {
    const value = call.args[key];
    if (typeof value === "string" && value) return value.split("\n")[0] ?? "";
  }
  return "";
}

/**
 * Whether "always allow" would take effect for this question. Without rules to add (as for a
 * network command once untrusted content has been read) it would only allow the call once,
 * so it isn't offered, as in the terminal.
 */
export function canAlwaysAllow(call: ToolCall): boolean {
  return (call.permission?.rules.length ?? 0) > 0;
}

/** The diff to show on a call's card: what it changed, or, until it has run, what it would. */
export function diffOf(call: ToolCall): string | null {
  if (call.result) return call.result.diff;
  return call.permission?.preview ?? null;
}

/** For a Write waiting for an answer: whether it makes a new file or replaces one. */
export function writeKind(call: ToolCall): string {
  const preview = call.permission?.state === "asking" ? call.permission.preview : null;
  if (call.name !== "Write" || preview === null) return "";
  return preview.startsWith("--- /dev/null") ? "New file" : "Replaces the existing file";
}
