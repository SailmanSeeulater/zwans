import { describe, expect, it } from "vitest";
import { attachProblem, changesFrom, describeUndo, MAX_IMAGES } from "./attachments";

describe("attachProblem", () => {
  it("takes the images the API takes, up to the limits", () => {
    expect(attachProblem({ name: "shot.png", type: "image/png", size: 1000 }, 0)).toBeNull();
    expect(attachProblem({ name: "a.svg", type: "image/svg+xml", size: 10 }, 0)).toMatch(/isn't a PNG/);
    expect(attachProblem({ name: "big.jpg", type: "image/jpeg", size: 4_000_000 }, 0)).toMatch(/4.0 MB/);
    expect(attachProblem({ name: "x.gif", type: "image/gif", size: 10 }, MAX_IMAGES)).toMatch(/at most 5/);
  });
});

describe("changesFrom", () => {
  const turns = [
    { turn: 3, prompt: "c", changes: [{ status: "changed" as const, path: "a.py" }] },
    {
      turn: 2,
      prompt: "b",
      changes: [
        { status: "added" as const, path: "a.py" },
        { status: "added" as const, path: "b.py" },
      ],
    },
    { turn: 1, prompt: "a", changes: [{ status: "changed" as const, path: "old.py" }] },
  ];

  it("lists each file once, as the earliest undone turn changed it", () => {
    expect(changesFrom(turns, 2)).toEqual([
      { status: "added", path: "a.py" },
      { status: "added", path: "b.py" },
    ]);
    expect(changesFrom(turns, 3)).toEqual([{ status: "changed", path: "a.py" }]);
  });
});

describe("describeUndo", () => {
  it("says what was removed and what was restored", () => {
    expect(
      describeUndo([
        { status: "deleted", path: "new.md" },
        { status: "changed", path: "calc.py" },
      ]),
    ).toBe("Removed new.md, which was new; restored calc.py.");
    expect(describeUndo([])).toBe("No files had changed since then.");
  });
});
