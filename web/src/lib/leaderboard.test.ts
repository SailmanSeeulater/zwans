import { describe, expect, it } from "vitest";
import { costScale, rateTicks } from "./leaderboard";

describe("costScale", () => {
  it("is linear from zero when the costs are close", () => {
    const scale = costScale([0.02, 0.04]);
    expect(scale.log).toBe(false);
    expect(scale.at(0)).toBe(0);
    expect(scale.at(0.04)).toBeCloseTo(1 / 1.1);
    expect(scale.ticks[0]).toBe(0);
  });

  it("is a log axis when they are far apart", () => {
    const scale = costScale([0.01, 0.1, 1]);
    expect(scale.log).toBe(true);
    // Equal ratios are equal distances.
    expect(scale.at(0.1) - scale.at(0.01)).toBeCloseTo(scale.at(1) - scale.at(0.1));
    expect(scale.at(0.01)).toBeGreaterThan(0);
    expect(scale.at(1)).toBeLessThan(1);
    expect(scale.ticks).toEqual([0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1].map((t) => expect.closeTo(t)));
  });

  it("stays linear when a row is free, and handles one row or none", () => {
    expect(costScale([0, 0.01, 5]).log).toBe(false);
    expect(costScale([3]).log).toBe(false);
    expect(costScale([0]).at(0)).toBe(0);
    expect(costScale([]).ticks).toHaveLength(5);
  });
});

describe("rateTicks", () => {
  const close = (ticks: number[]) => ticks.map((t) => expect.closeTo(t));

  it("starts as high as the rows allow, at a round number", () => {
    expect(rateTicks([1, 0.93])).toEqual(close([0.9, 0.92, 0.94, 0.96, 0.98, 1]));
    expect(rateTicks([1, 0.86])).toEqual(close([0.8, 0.85, 0.9, 0.95, 1]));
    expect(rateTicks([1, 0.6])).toEqual(close([0.5, 0.6, 0.7, 0.8, 0.9, 1]));
    expect(rateTicks([1, 0.24])).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(rateTicks([])).toHaveLength(6);
  });
});
