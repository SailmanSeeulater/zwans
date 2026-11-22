import { describe, expect, it } from "vitest";
import { activity, contextShare, diffBlocks, diffStat, kindOf, outcomeOf, shortTokens } from "./activity";
import type { ToolCall, Turn } from "./events";

function call(id: string, name: string, result?: { content: string; isError?: boolean }): ToolCall {
  return {
    id,
    name,
    args: {},
    hooks: [],
    subcalls: [],
    result: result && { content: result.content, isError: result.isError ?? false, untrusted: false, diff: null },
  };
}

function turn(...calls: ToolCall[]): Turn {
  return {
    prompt: "p",
    number: 1,
    images: 0,
    items: [{ kind: "text", text: "Looking." }, ...calls.map((c) => ({ kind: "tool" as const, call: c }))],
    modelCalls: 1,
    inputTokens: 0,
    outputTokens: 0,
  };
}

describe("kindOf", () => {
  it("sorts tools into reading, editing and running", () => {
    expect(["Read", "Grep", "Edit", "Write", "Bash", "RunTests", "Mystery"].map(kindOf)).toEqual([
      "read",
      "read",
      "edit",
      "edit",
      "run",
      "run",
      "other",
    ]);
  });
});

describe("outcomeOf", () => {
  it("reads how the tests went from RunTests' first line", () => {
    expect(outcomeOf(call("a", "RunTests", { content: "Tests failed.\n\n## pytest failed" }))).toBe("failed");
    expect(outcomeOf(call("a", "RunTests", { content: "All tests passed.\npytest: 3 passed" }))).toBe("passed");
  });

  it("reads a test command run with Bash by its exit code, and leaves other commands alone", () => {
    const bash = (command: string, content: string) => ({ ...call("a", "Bash", { content }), args: { command } });
    expect(outcomeOf(bash("python3 -m unittest -q", "FAILED (failures=1)\n(exit code 1)"))).toBe("failed");
    expect(outcomeOf(bash("cd web && npm test", "ok\n(exit code 0)"))).toBe("passed");
    expect(outcomeOf(bash("grep -r TODO src", "\n(exit code 1)"))).toBeNull();
  });

  it("marks a call that failed, and nothing for one still running", () => {
    expect(outcomeOf(call("a", "Bash", { content: "exit code 1", isError: true }))).toBe("error");
    expect(outcomeOf(call("a", "Bash", { content: "ok" }))).toBeNull();
    expect(outcomeOf(call("a", "Bash"))).toBeNull();
  });
});

describe("activity", () => {
  it("has a mark per call, by turn, without the plan or questions", () => {
    const marks = activity(
      [
        turn(call("1", "Read", { content: "x" }), call("2", "TodoWrite", { content: "" })),
        turn(call("3", "Edit", { content: "ok" }), call("4", "RunTests", { content: "All tests passed." })),
      ],
      (c) => (c.name === "Read" ? "calc.py" : ""),
    );
    expect(marks).toEqual([
      { id: "1", turn: 0, kind: "read", outcome: null, label: "Read calc.py" },
      { id: "3", turn: 1, kind: "edit", outcome: null, label: "Edit" },
      { id: "4", turn: 1, kind: "run", outcome: "passed", label: "RunTests (tests passed)" },
    ]);
  });
});

describe("diffStat", () => {
  it("counts added and removed lines, not the file headers", () => {
    const diff = "--- a/calc.py\n+++ b/calc.py\n@@ -1,3 +1,3 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n+\n";
    expect(diffStat(diff)).toEqual({ added: 2, removed: 1 });
  });
});

describe("diffBlocks", () => {
  it("splits five blocks in proportion", () => {
    expect(diffBlocks(30, 10)).toEqual(["add", "add", "add", "add", "del"]);
    expect(diffBlocks(0, 40)).toEqual(["del", "del", "del", "del", "del"]);
  });

  it("gives any change at least one block, and leaves the rest of a small change empty", () => {
    expect(diffBlocks(100, 1)).toEqual(["add", "add", "add", "add", "del"]);
    expect(diffBlocks(1, 1)).toEqual(["add", "del", "none", "none", "none"]);
    expect(diffBlocks(0, 0)).toEqual(["none", "none", "none", "none", "none"]);
  });
});

describe("contextShare", () => {
  it("is the share of the way to compaction, never past it", () => {
    expect(contextShare(40_000, 160_000)).toBe(0.25);
    expect(contextShare(200_000, 160_000)).toBe(1);
    expect(contextShare(10, 0)).toBe(0);
  });
});

describe("shortTokens", () => {
  it("rounds to what fits in a small label", () => {
    expect([950, 1234, 12_345, 160_000, 1_500_000].map(shortTokens)).toEqual(["950", "1.2k", "12k", "160k", "1.5M"]);
  });
});
