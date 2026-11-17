import { describe, expect, it } from "vitest";
import { askedFor, buildCalls, cacheHitRate, costParts, latestTurnCall, uncachedCost } from "./calls";
import type { RawEvent } from "./events";

const HAIKU = { input: 0.1, output: 0.5, cache_write: 0.125, cache_read: 0.01 };
const split = { system: 100, tools: 200, messages: 50, tool_results: 0 };

describe("buildCalls", () => {
  it("numbers calls across turns, ties compactions to their summary call, and marks tool errors", () => {
    const events: RawEvent[] = [
      { type: "turn_started", prompt: "One" },
      {
        type: "model_call",
        time: "2026-11-16T10:00:02.000Z",
        seconds: 2,
        model: "claude-haiku-5-5",
        stop_reason: "tool_use",
        tools: ["Bash", "Bash"],
        input_tokens: 10,
        cache_write_tokens: 1_000,
        output_tokens: 50,
        prices: HAIKU,
        context: split,
      },
      { type: "tool_call_requested", call_id: "t1", name: "Bash", args: {} },
      { type: "tool_result", call_id: "t1", content: "boom", is_error: true },
      { type: "model_call", stop_reason: "end_turn", input_tokens: 10, cache_read_tokens: 1_000, output_tokens: 5 },
      { type: "turn_started", prompt: "Two" },
      { type: "context_compacted", tokens_before: 9_000, tokens_after: 900, summary: "Notes." },
      { type: "model_call", purpose: "summary", stop_reason: "end_turn", input_tokens: 800, output_tokens: 90 },
      { type: "model_call", stop_reason: "end_turn", input_tokens: 900, output_tokens: 20 },
    ];

    const { calls, compactions } = buildCalls(events);

    expect(calls.map((c) => [c.n, c.turn, c.purpose])).toEqual([
      [1, 1, "turn"],
      [2, 1, "turn"],
      [3, 2, "summary"],
      [4, 2, "turn"],
    ]);
    expect(calls[0]!.toolError).toBe(true);
    expect(calls[1]!.toolError).toBe(false);
    expect(askedFor(calls[0]!)).toBe("Bash ×2");
    expect(askedFor(calls[1]!)).toBe("Answer");
    expect(compactions).toEqual([
      expect.objectContaining({ turn: 2, beforeCall: 4, tokensBefore: 9_000, summary: "Notes.", call: calls[2] }),
    ]);
    expect(latestTurnCall(calls)?.n).toBe(4);
    expect(cacheHitRate(calls.slice(0, 2))).toBeCloseTo(1_000 / 2_020);
  });

  it("prices a call's parts, and the same call without the cache", () => {
    const [call] = buildCalls([
      { type: "model_call", input_tokens: 0, cache_read_tokens: 1_000_000, output_tokens: 0, prices: HAIKU },
    ]).calls;
    expect(costParts(call!)?.cacheRead).toBeCloseTo(0.01);
    expect(uncachedCost(call!)).toBeCloseTo(0.1);
  });

  it("counts a subagent's calls with its task", () => {
    const { calls } = buildCalls([
      { type: "turn_started", prompt: "Go" },
      { type: "subagent", task: "Find the tests", event: { type: "model_call", input_tokens: 5 } },
    ]);
    expect(calls[0]!.subagent).toBe("Find the tests");
  });
});
