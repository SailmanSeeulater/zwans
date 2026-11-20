import { describe, expect, it } from "vitest";
import { buildTurns, canAlwaysAllow, diffOf, waitingCalls, writeKind, type RawEvent, type ToolCall } from "./events";

describe("buildTurns", () => {
  it("groups text, calls, results, diffs and questions into turns", () => {
    const events: RawEvent[] = [
      { type: "turn_started", prompt: "Fix the bug." },
      { type: "text_delta", text: "Looking" },
      { type: "text_delta", text: " now." },
      { type: "tool_call_requested", call_id: "c1", name: "Edit", args: { path: "a.py" } },
      { type: "permission_requested", call_id: "c1", reason: "Edit a.py changes files", rules: ["Edit(a.py)"] },
      { type: "permission_resolved", call_id: "c1", allowed: true },
      { type: "tool_result", call_id: "c1", content: "Replaced 1 occurrence in a.py.", diff: "--- a/a.py\n" },
      { type: "usage_updated", input_tokens: 10, output_tokens: 5, cache_read_tokens: 90 },
      { type: "turn_ended", stop_reason: "end_turn" },
      { type: "turn_started", prompt: "Now push." },
      { type: "tool_call_requested", call_id: "c2", name: "Bash", args: { command: "git push" } },
      { type: "permission_requested", call_id: "c2", reason: "`git push` uses the network", rules: [] },
    ];

    const turns = buildTurns(events);

    expect(turns.map((t) => t.prompt)).toEqual(["Fix the bug.", "Now push."]);
    const [first, second] = turns;
    expect(first!.items[0]).toEqual({ kind: "text", text: "Looking now." });
    const edit = first!.items[1];
    expect(edit?.kind === "tool" && edit.call.permission?.state).toBe("allowed");
    expect(edit?.kind === "tool" && edit.call.result?.diff).toBe("--- a/a.py\n");
    expect(first!.stop?.reason).toBe("end_turn");
    expect([first!.modelCalls, first!.inputTokens, first!.outputTokens]).toEqual([1, 100, 5]);
    expect(second!.stop).toBeUndefined();
    expect(waitingCalls(turns).map((c) => c.id)).toEqual(["c2"]);
  });

  it("puts a subagent's calls under the Task call that started it", () => {
    const events: RawEvent[] = [
      { type: "turn_started", prompt: "Find it." },
      { type: "tool_call_requested", call_id: "t1", name: "Task", args: { description: "search", prompt: "..." } },
      {
        type: "subagent",
        task: "search",
        event: { type: "tool_call_requested", call_id: "s1", name: "Grep", args: { pattern: "load" } },
      },
      { type: "subagent", task: "search", event: { type: "text_delta", text: "ignored" } },
      { type: "subagent", task: "search", event: { type: "tool_result", call_id: "s1", content: "x.py:3" } },
      { type: "tool_result", call_id: "t1", content: "It's in x.py." },
    ];

    const [turn] = buildTurns(events);
    const task = turn!.items[0];

    expect(turn!.items).toHaveLength(1);
    expect(task?.kind === "tool" && task.call.subcalls.map((c) => [c.name, c.result?.content])).toEqual([
      ["Grep", "x.py:3"],
    ]);
  });
});

describe("permission questions", () => {
  const ask = (rules: string[], preview?: string): ToolCall => {
    const events: RawEvent[] = [
      { type: "turn_started", prompt: "Go." },
      { type: "tool_call_requested", call_id: "w", name: "Write", args: { path: "a.py", content: "x = 1\n" } },
      { type: "permission_requested", call_id: "w", reason: "Write a.py changes files", rules, preview },
    ];
    const item = buildTurns(events)[0]!.items[0];
    if (item?.kind !== "tool") throw new Error("no call");
    return item.call;
  };

  it("offers always only when there are rules for it to add", () => {
    expect(canAlwaysAllow(ask(["Write(a.py)"]))).toBe(true);
    expect(canAlwaysAllow(ask([]))).toBe(false);
  });

  it("shows the diff a Write would make, and whether it makes a new file", () => {
    const created = ask([], "--- /dev/null\n+++ b/a.py\n@@ -0,0 +1 @@\n+x = 1\n");
    expect(diffOf(created)).toContain("+x = 1");
    expect(writeKind(created)).toBe("New file");
    const replaced = ask([], "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-y = 2\n+x = 1\n");
    expect(writeKind(replaced)).toBe("Replaces the existing file");
    expect(diffOf(ask([]))).toBeNull();
  });

  it("shows what a call changed once it has run, not the preview", () => {
    const call = ask([], "--- /dev/null\n+++ b/a.py\n");
    call.permission!.state = "declined";
    call.result = { content: "Declined.", isError: true, untrusted: false, diff: null };
    expect(diffOf(call)).toBeNull();
    expect(writeKind(call)).toBe("");
  });
});
