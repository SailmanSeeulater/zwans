import { describe, expect, it } from "vitest";
import type { Item, ToolCall, Turn } from "./events";
import { elapsed, livenessOf, phaseOf, tabTitle, turnStartedAt } from "./working";

function call(name: string, args: Record<string, unknown>, more: Partial<ToolCall> = {}): ToolCall {
  return { id: name, name, args, hooks: [], subcalls: [], ...more };
}
const done = { content: "ok", isError: false, untrusted: false, diff: null };

function turn(...items: Item[]): Turn[] {
  return [{ prompt: "p", number: 1, images: 0, items, modelCalls: 0, inputTokens: 0, outputTokens: 0 }];
}

describe("phaseOf", () => {
  it("is thinking before anything arrives and after a call finishes", () => {
    expect(phaseOf([])).toEqual({ verb: "Thinking", detail: "" });
    expect(phaseOf(turn())).toEqual({ verb: "Thinking", detail: "" });
    expect(phaseOf(turn({ kind: "tool", call: call("Read", { path: "a.py" }, { result: done }) })).verb).toBe("Thinking");
    expect(phaseOf(turn({ kind: "note", text: "Hm." })).verb).toBe("Thinking");
  });

  it("names a call that's still running, and what it's working on", () => {
    expect(phaseOf(turn({ kind: "tool", call: call("Read", { path: "calc.py" }) }))).toEqual({
      verb: "Reading",
      detail: "calc.py",
    });
    expect(phaseOf(turn({ kind: "tool", call: call("RunTests", {}) })).verb).toBe("Running the tests");
    expect(phaseOf(turn({ kind: "tool", call: call("Mystery", {}) })).verb).toBe("Using Mystery");
  });

  it("is writing while text arrives", () => {
    expect(phaseOf(turn({ kind: "text", text: "The bug is" })).verb).toBe("Writing");
  });

  it("waits for you while a call asks, and looks inside a subagent", () => {
    const asking = call("Bash", { command: "rm x" }, {
      permission: { state: "asking", reason: "", rules: [], preview: null },
    });
    expect(phaseOf(turn({ kind: "tool", call: asking })).verb).toBe("Waiting for you");
    const task = call("Task", { description: "look" }, {
      subcalls: [call("Read", { path: "a.py" }, { result: done }), call("Grep", { pattern: "total" })],
    });
    expect(phaseOf(turn({ kind: "tool", call: task }))).toEqual({ verb: "Searching", detail: "total" });
  });
});

describe("turnStartedAt", () => {
  it("is the latest turn's start, or null without times", () => {
    const events = [
      { type: "turn_started", time: "2026-11-22T10:00:00.000Z" },
      { type: "turn_ended", time: "2026-11-22T10:00:05.000Z" },
      { type: "turn_started", time: "2026-11-22T10:01:00.000Z" },
      { type: "text_delta", time: "2026-11-22T10:01:01.000Z" },
    ];
    expect(turnStartedAt(events)).toBe(Date.parse("2026-11-22T10:01:00.000Z"));
    expect(turnStartedAt([{ type: "turn_started" }])).toBeNull();
    expect(turnStartedAt([])).toBeNull();
  });
});

describe("elapsed", () => {
  it("reads as a clock would say it", () => {
    expect([0, 7, 65, 600, 3700].map(elapsed)).toEqual(["0s", "7s", "1m 05s", "10m 00s", "1h 01m"]);
  });
});

describe("livenessOf and tabTitle", () => {
  it("tells working from waiting from idle", () => {
    expect(livenessOf({ running: true, waiting_for: [] })).toBe("working");
    expect(livenessOf({ running: true, waiting_for: ["c1"] })).toBe("waiting");
    expect(livenessOf({ running: false, waiting_for: [] })).toBe("idle");
    expect(livenessOf(null)).toBe("idle");
  });

  it("marks the tab while it works and counts what's waiting", () => {
    expect(tabTitle("Fix the parser", "idle", 0)).toBe("Fix the parser · Zwans");
    expect(tabTitle("Fix the parser", "working", 0)).toBe("◌ Fix the parser · Zwans");
    expect(tabTitle("Fix the parser", "waiting", 2)).toBe("(2) Fix the parser · Zwans");
    expect(tabTitle("", "idle", 0)).toBe("Zwans");
  });
});
