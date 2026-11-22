import { describe, expect, it } from "vitest";
import { axisTicks, bucketLabel, labelled } from "./usage";

describe("bucketLabel", () => {
  it("names a bucket by its first day, as its period reads", () => {
    expect(bucketLabel("2026-11-22", "day")).toBe("Nov 22");
    expect(bucketLabel("2026-11-16", "week")).toBe("Nov 16");
    expect(bucketLabel("2026-11-01", "month")).toBe("Nov 2026");
    expect(bucketLabel("2026-01-01", "year")).toBe("2026");
  });
});

describe("axisTicks", () => {
  it("gives round steps from zero to at least the largest value", () => {
    expect(axisTicks(1_870_000)).toEqual([0, 500_000, 1_000_000, 1_500_000, 2_000_000]);
    expect(axisTicks(40)).toEqual([0, 10, 20, 30, 40]);
    expect(axisTicks(0.83)).toEqual([0, 0.25, 0.5, 0.75, 1]);
  });

  it("still gives an axis when nothing was used", () => {
    expect(axisTicks(0)).toEqual([0, 1]);
  });

  it("never stops short of the largest value", () => {
    for (const most of [1, 3, 7, 99, 101, 12_345, 0.004]) {
      expect(axisTicks(most).at(-1)).toBeGreaterThanOrEqual(most);
    }
  });
});

describe("labelled", () => {
  it("labels every bar when there are few, and about eight when there are many", () => {
    expect([...labelled(4)].sort()).toEqual([0, 1, 2, 3]);
    const thirty = labelled(30);
    expect(thirty.has(29)).toBe(true); // the newest always has one
    expect(thirty.size).toBeLessThanOrEqual(8);
    expect(thirty.size).toBeGreaterThanOrEqual(6);
  });
});
