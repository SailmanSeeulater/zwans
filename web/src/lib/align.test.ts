import { describe, expect, it } from "vitest";
import { align, firstDivergence, normalize, toSteps } from "./align";
import type { RawEvent } from "./events";

function call(id: string, name: string, args: Record<string, unknown>, content = "ok", isError = false) {
  return [
    { type: "tool_call_requested", call_id: id, name, args },
    { type: "tool_result", call_id: id, content, is_error: isError },
  ];
}

function transcript(...parts: RawEvent[][]): RawEvent[] {
  return [{ type: "turn_started", prompt: "Fix it." }, ...parts.flat(), { type: "turn_ended", stop_reason: "end_turn" }];
}

describe("toSteps", () => {
  it("makes a step of each tool call and each stretch of text", () => {
    const steps = toSteps(
      transcript(
        [{ type: "text_delta", text: "Let me " }, { type: "text_delta", text: "look." }],
        call("1", "Read", { path: "calc.py" }),
        call("2", "Bash", { command: "pytest -q\nmore" }, "1 failed", true),
      ),
    );
    expect(steps.map((s) => [s.kind, s.label, s.isError])).toEqual([
      ["text", "Let me look.", false],
      ["call", "Read calc.py", false],
      ["call", "Bash pytest -q", true],
    ]);
  });
});

describe("normalize", () => {
  it("takes out the attempt's own folder, so two runs' commands can match", () => {
    const a = "cd /var/folders/x/T/zwans-eval-stockroom-tenants-8cmkfa7x/work && pytest -q";
    const b = "cd /tmp/zwans-eval-stockroom-tenants-wa0izs_z/work && pytest -q";
    expect(normalize(a)).toBe("pytest -q");
    expect(normalize(b)).toBe("pytest -q");
    expect(normalize("/tmp/zwans-eval-x-1ab/work/src/a.py")).toBe("./src/a.py");
    expect(normalize("git status")).toBe("git status");
  });
});

describe("align", () => {
  it("keeps the common steps side by side and finds the first difference", () => {
    const a = toSteps(
      transcript(call("1", "Read", { path: "calc.py" }), call("2", "Edit", { path: "calc.py" }), call("3", "Bash", { command: "pytest" })),
    );
    const b = toSteps(
      transcript(
        call("1", "Read", { path: "calc.py" }),
        call("2", "Read", { path: "tests/test_calc.py" }),
        call("3", "Edit", { path: "calc.py" }),
        call("4", "Bash", { command: "pytest" }, "1 failed", true),
      ),
    );

    const rows = align(a, b);

    expect(rows.map((r) => [r.a?.label ?? null, r.b?.label ?? null, r.same])).toEqual([
      ["Read calc.py", "Read calc.py", true],
      [null, "Read tests/test_calc.py", false],
      ["Edit calc.py", "Edit calc.py", true],
      ["Bash pytest", "Bash pytest", false], // same call, but it failed in B
    ]);
    expect(firstDivergence(rows)).toBe(1);
  });

  it("says -1 when the runs never part", () => {
    const steps = toSteps(transcript(call("1", "Read", { path: "a.py" })));
    expect(firstDivergence(align(steps, steps))).toBe(-1);
  });
});
