import { describe, expect, it } from "vitest";
import { calendarGrid, dayLabel, level, type UsageCalendar } from "./calendar";

const day = (d: string, tokens: number) => ({ day: d, tokens, dollars: tokens / 1000, calls: 1, sessions: 1 });

describe("calendarGrid", () => {
  const calendar: UsageCalendar = {
    start: "2026-10-26", // a Monday
    end: "2026-11-19", // a Thursday
    days: [day("2026-11-01", 100), day("2026-11-17", 400), day("2026-11-18", 25), day("2026-11-19", 1)],
  };

  it("lays the days out in Monday-first weeks, the days after today left blank", () => {
    const grid = calendarGrid(calendar, "tokens");
    expect(grid.weeks).toHaveLength(4);
    expect(grid.weeks[0]?.[0]?.day).toBe("2026-10-26");
    expect(grid.weeks[3]?.map((c) => c.future)).toEqual([false, false, false, false, true, true, true]);
    expect(grid.weeks[3]?.[1]).toMatchObject({ day: "2026-11-17", level: 4 });
    // October's last days are too few to label; November's label goes over its first week.
    expect(grid.months).toEqual([{ column: 1, label: "Nov" }]);
  });

  it("counts the active days and the streaks", () => {
    const grid = calendarGrid(calendar, "tokens");
    expect([grid.activeDays, grid.longestStreak, grid.currentStreak]).toEqual([4, 3, 3]);
    const notToday = calendarGrid({ ...calendar, days: calendar.days.slice(0, 3) }, "tokens");
    expect(notToday.currentStreak).toBe(2); // today can still be used
  });
});

describe("level", () => {
  it("spreads quiet days out and keeps nothing at zero", () => {
    expect([0, 1, 50, 150, 400].map((v) => level(v, 400))).toEqual([0, 1, 2, 3, 4]);
    expect(level(5, 0)).toBe(0);
  });
});

it("names a day for its tooltip", () => {
  expect(dayLabel("2026-11-19")).toBe("Thu, Nov 19");
});
