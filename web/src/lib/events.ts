/**
 * Turns Zwans's event stream (src/zwans/events.py) into a conversation to show: turns, each
 * with the model's text, its tool calls and their results, and what the user was asked.
 * The live session view and the eval transcript view both use it.
 */

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
  result?: { content: string; isError: boolean; untrusted: boolean; diff: string | null };
  permission?: { state: PermissionState; reason: string; rules: string[] };
  hooks: { event: string; message: string }[];
  /** For a Task call: what its subagent did. */
  subcalls: ToolCall[];
}

export type Item =
  | { kind: "text"; text: string }
  | { kind: "note"; text: string }
  | { kind: "tool"; call: ToolCall }
  | { kind: "error"; message: string }
  | { kind: "compacted"; before: number; after: number }
  | { kind: "hook"; event: string; message: string };

export interface Turn {
  prompt: string;
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

  const current = (): Turn => {
    let turn = turns.at(-1);
    if (!turn) {
      turn = { prompt: "", items: [], modelCalls: 0, inputTokens: 0, outputTokens: 0 };
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
          hooks: [],
          subcalls: [],
        };
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
          call.permission = { state: "asking", reason: str(event.reason), rules };
        }
        break;
      }
      case "permission_resolved": {
        const call = calls.get(str(event.call_id));
        if (call?.permission) call.permission.state = event.allowed ? "allowed" : "declined";
        break;
      }
      case "permission_denied": {
        const call = calls.get(str(event.call_id));
        if (call) call.permission = { state: "denied", reason: str(event.reason), rules: [] };
        break;
      }
      case "tool_result": {
        const call = calls.get(str(event.call_id));
        if (call) {
          call.result = {
            content: str(event.content),
            isError: Boolean(event.is_error),
            untrusted: Boolean(event.untrusted),
            diff: typeof event.diff === "string" ? event.diff : null,
          };
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
          });
        }
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

/** The one argument worth showing for a call, so it fits on a line. */
export function keyArgument(call: Pick<ToolCall, "name" | "args">): string {
  for (const key of ["command", "path", "pattern", "description", "name", "ticket"]) {
    const value = call.args[key];
    if (typeof value === "string" && value) return value.split("\n")[0] ?? "";
  }
  return "";
}
