import { describe, expect, it } from "vitest";
import type { ToolCall, Turn } from "./events";
import { handoffPrompt, modelName, stuckReason } from "./handoff";

const call = (name: string, args: Record<string, unknown>, content: string, isError = false): ToolCall => ({
  id: `${name}${content.length}`,
  name,
  args,
  hooks: [],
  subcalls: [],
  result: { content, isError, untrusted: false, diff: null },
});

const turn = (reason: string, ...calls: ToolCall[]): Turn => ({
  prompt: "Fix it",
  number: 1,
  images: 0,
  items: calls.map((c) => ({ kind: "tool" as const, call: c })),
  stop: { reason, detail: "" },
  modelCalls: 1,
  inputTokens: 0,
  outputTokens: 0,
});

describe("stuckReason", () => {
  it("reads a turn that hit a limit or an error as stuck, and a stopped one as not", () => {
    expect(stuckReason(turn("max_steps"))).toBe("ran out of steps before finishing");
    expect(stuckReason(turn("error"))).toBe("stopped on an error");
    expect(stuckReason(turn("interrupted"))).toBeNull();
    expect(stuckReason(undefined)).toBeNull();
  });

  it("reads tests left failing, or many failed calls, as stuck", () => {
    const failing = call("Bash", { command: "pytest -q" }, "1 failed (exit code 1)");
    const passing = call("Bash", { command: "pytest -q" }, "3 passed (exit code 0)");
    expect(stuckReason(turn("end_turn", failing))).toBe("finished with the tests still failing");
    expect(stuckReason(turn("end_turn", failing, passing))).toBeNull();
    const broken = [1, 2, 3].map((n) => call("Edit", {}, "x".repeat(n), true));
    expect(stuckReason(turn("end_turn", ...broken))).toBe("had 3 tool calls fail");
    expect(stuckReason(turn("end_turn", ...broken.slice(0, 2)))).toBeNull();
  });
});

describe("handing off", () => {
  it("names the models and tells the new one what it's picking up", () => {
    expect(modelName("claude-sonnet-5-5")).toBe("Claude Sonnet 5.5");
    expect(modelName("ollama/qwen3-coder:30b")).toBe("qwen3-coder:30b");
    expect(handoffPrompt("qwen3-coder:30b", "ran out of steps before finishing")).toMatch(
      /^You're taking over this task from qwen3-coder:30b, which ran out of steps/,
    );
  });
});
