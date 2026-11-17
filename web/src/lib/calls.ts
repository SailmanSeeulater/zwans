/**
 * What happened under the hood: every model call and compaction, from the `model_call` and
 * `context_compacted` events (src/zwans/events.py). The side panel and the inspector use it.
 */

import type { RawEvent } from "./events";

export interface ContextSplit {
  system: number;
  tools: number;
  messages: number;
  tool_results: number;
}

/** Dollars per million tokens. */
export interface Prices {
  input: number;
  output: number;
  cache_write: number;
  cache_read: number;
}

export interface ModelCall {
  /** 1-based, across the session: the main loop's calls, summaries and subagents' calls. */
  n: number;
  /** The turn it belongs to, 1-based. */
  turn: number;
  purpose: "turn" | "summary";
  /** For a subagent's call: the description of its Task. */
  subagent: string | null;
  model: string;
  stopReason: string;
  seconds: number;
  firstTokenSeconds: number | null;
  /** When it ended, in ms since the epoch; NaN when the events carry no times. */
  endedAt: number;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  dollars: number | null;
  prices: Prices | null;
  tools: string[];
  context: ContextSplit;
  /** Whether a tool it asked for came back as an error. */
  toolError: boolean;
}

export interface Compaction {
  turn: number;
  /** The number of the call it made room for. */
  beforeCall: number;
  tokensBefore: number;
  tokensAfter: number;
  summary: string;
  /** The model call that wrote the summary. */
  call: ModelCall | null;
}

export interface UnderTheHood {
  calls: ModelCall[];
  compactions: Compaction[];
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");
const num = (value: unknown): number => (typeof value === "number" ? value : 0);
const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" ? (value as Record<string, unknown>) : {};

function splitOf(value: unknown): ContextSplit {
  const o = obj(value);
  return { system: num(o.system), tools: num(o.tools), messages: num(o.messages), tool_results: num(o.tool_results) };
}

function pricesOf(value: unknown): Prices | null {
  if (!value || typeof value !== "object") return null;
  const o = obj(value);
  return { input: num(o.input), output: num(o.output), cache_write: num(o.cache_write), cache_read: num(o.cache_read) };
}

/** Every model call, in order, with the compactions between them. */
export function buildCalls(events: RawEvent[]): UnderTheHood {
  const calls: ModelCall[] = [];
  const compactions: Compaction[] = [];
  const askedBy = new Map<string, ModelCall>(); // tool call id → the model call that asked for it
  let turn = 0;
  let lastMain: ModelCall | null = null;

  const add = (event: RawEvent, subagent: string | null): ModelCall => {
    const call: ModelCall = {
      n: calls.length + 1,
      turn: Math.max(turn, 1),
      purpose: event.purpose === "summary" ? "summary" : "turn",
      subagent,
      model: str(event.model),
      stopReason: str(event.stop_reason),
      seconds: num(event.seconds),
      firstTokenSeconds: typeof event.first_token_seconds === "number" ? event.first_token_seconds : null,
      endedAt: event.time ? Date.parse(str(event.time)) : NaN,
      input: num(event.input_tokens),
      output: num(event.output_tokens),
      cacheRead: num(event.cache_read_tokens),
      cacheWrite: num(event.cache_write_tokens),
      dollars: typeof event.dollars === "number" ? event.dollars : null,
      prices: pricesOf(event.prices),
      tools: Array.isArray(event.tools) ? event.tools.map(String) : [],
      context: splitOf(event.context),
      toolError: false,
    };
    calls.push(call);
    return call;
  };

  for (const event of events) {
    switch (event.type) {
      case "turn_started":
        turn += 1;
        break;
      case "model_call": {
        const call = add(event, null);
        const last = compactions.at(-1);
        if (call.purpose === "summary") {
          if (last && !last.call) {
            last.call = call;
            last.beforeCall = call.n + 1;
          }
        } else {
          lastMain = call;
        }
        break;
      }
      case "subagent": {
        const inner = obj(event.event) as RawEvent;
        if (inner.type === "model_call") add({ ...inner, time: inner.time ?? event.time }, str(event.task));
        break;
      }
      case "tool_call_requested":
        if (lastMain) askedBy.set(str(event.call_id), lastMain);
        break;
      case "tool_result": {
        const call = askedBy.get(str(event.call_id));
        if (call && event.is_error) call.toolError = true;
        break;
      }
      case "context_compacted":
        compactions.push({
          turn: Math.max(turn, 1),
          beforeCall: calls.length + 1,
          tokensBefore: num(event.tokens_before),
          tokensAfter: num(event.tokens_after),
          summary: str(event.summary),
          call: null,
        });
        break;
    }
  }
  return { calls, compactions };
}

export const contextTotal = (c: ContextSplit): number => c.system + c.tools + c.messages + c.tool_results;

/** Input tokens the API counted for a call, cached or not. */
export const counted = (c: ModelCall): number => c.input + c.cacheRead + c.cacheWrite;

/** The share of input tokens that were read from the cache. */
export function cacheHitRate(calls: ModelCall[]): number {
  const total = calls.reduce((sum, c) => sum + counted(c), 0);
  return total ? calls.reduce((sum, c) => sum + c.cacheRead, 0) / total : 0;
}

export interface CostParts {
  input: number;
  cacheWrite: number;
  cacheRead: number;
  output: number;
}

/** What each part of a call cost, in dollars; null when the model's price isn't known. */
export function costParts(c: ModelCall): CostParts | null {
  if (!c.prices) return null;
  const m = 1_000_000;
  return {
    input: (c.input * c.prices.input) / m,
    cacheWrite: (c.cacheWrite * c.prices.cache_write) / m,
    cacheRead: (c.cacheRead * c.prices.cache_read) / m,
    output: (c.output * c.prices.output) / m,
  };
}

/** What a call would have cost with no cache: every input token at the full input price. */
export function uncachedCost(c: ModelCall): number | null {
  if (!c.prices) return null;
  return (counted(c) * c.prices.input + c.output * c.prices.output) / 1_000_000;
}

/** The main loop's last call: its context is what the conversation holds now. */
export function latestTurnCall(calls: ModelCall[]): ModelCall | undefined {
  return calls.findLast((c) => c.purpose === "turn" && !c.subagent);
}

/** A short description of what a call asked for. */
export function askedFor(c: ModelCall): string {
  if (c.purpose === "summary") return "Summary, for compaction";
  if (c.tools.length === 0) return c.stopReason === "end_turn" ? "Answer" : `Stopped: ${c.stopReason}`;
  const counts = new Map<string, number>();
  for (const t of c.tools) counts.set(t, (counts.get(t) ?? 0) + 1);
  return [...counts].map(([t, k]) => (k > 1 ? `${t} ×${k}` : t)).join(", ");
}

/** When a call started, in ms; NaN without times. */
export const startedAt = (c: ModelCall): number => c.endedAt - c.seconds * 1000;
