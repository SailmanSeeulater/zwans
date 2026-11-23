import { describe, expect, it } from "vitest";
import { laneState, readBudget, shares } from "./race";

describe("laneState", () => {
  it("puts a question first, then work, then how the last turn ended", () => {
    expect(laneState(true, true, [])).toBe("waiting");
    expect(laneState(true, false, [])).toBe("working");
    expect(laneState(false, false, [])).toBe("starting");
    expect(laneState(false, false, [{ type: "turn_ended", stop_reason: "end_turn" }])).toBe("done");
    expect(
      laneState(false, false, [
        { type: "turn_ended", stop_reason: "end_turn" },
        { type: "turn_ended", stop_reason: "budget" },
      ]),
    ).toBe("budget");
  });
});

describe("shares", () => {
  it("measures against the budget, or against what was spent when there's none", () => {
    expect(shares([1, 1.5], 5)).toEqual([0.2, 0.3]);
    expect(shares([1, 3], null)).toEqual([0.25, 0.75]);
    expect(shares([0, 0], null)).toEqual([0, 0]);
  });

  it("still fits once the spending passes the budget", () => {
    const [a, b] = shares([3, 3], 5);
    expect((a ?? 0) + (b ?? 0)).toBeCloseTo(1);
  });
});

describe("readBudget", () => {
  it("reads dollars, and none for blank or off", () => {
    expect(readBudget("$5")).toBe(5);
    expect(readBudget("0.50")).toBe(0.5);
    expect(readBudget("")).toBeNull();
    expect(readBudget("off")).toBeNull();
    expect(readBudget("-1")).toBeNaN();
    expect(readBudget("lots")).toBeNaN();
  });
});
