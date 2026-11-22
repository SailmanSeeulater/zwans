"use client";

import { useMemo, useState } from "react";
import { calendarGrid, dayLabel, type Cell, type UsageCalendar as Data } from "@/lib/calendar";
import { dollars, plural, tokens } from "@/lib/format";

const ROWS = ["Mon", "", "Wed", "", "Fri", "", ""];

/** A year of days, shaded by how much each used, with the streaks it makes. */
export function UsageCalendar({ data, measure }: { data: Data; measure: "tokens" | "dollars" }) {
  const grid = useMemo(() => calendarGrid(data, measure), [data, measure]);
  const [hover, setHover] = useState<{ cell: Cell; x: number; y: number } | null>(null);

  const describe = (cell: Cell) =>
    cell.used
      ? `${dayLabel(cell.day)}: ${tokens(cell.used.tokens)} tokens, ${dollars(cell.used.dollars)}, ${plural(cell.used.sessions, "session")}`
      : `${dayLabel(cell.day)}: nothing used`;

  return (
    <div className="calendar panel glass">
      <div className="calendar-stats">
        <span>
          <strong>{grid.activeDays}</strong> active {grid.activeDays === 1 ? "day" : "days"}
        </span>
        <span>
          <strong>{grid.currentStreak}</strong> day streak now
        </span>
        <span>
          Longest: <strong>{grid.longestStreak}</strong> {grid.longestStreak === 1 ? "day" : "days"}
        </span>
      </div>
      <div className="calendar-scroll" onMouseLeave={() => setHover(null)}>
        <div className="calendar-body" style={{ ["--weeks" as string]: grid.weeks.length }}>
          <div className="calendar-months" aria-hidden="true">
            {grid.months.map((m) => (
              <span key={m.column} style={{ gridColumn: m.column + 1 }}>
                {m.label}
              </span>
            ))}
          </div>
          <div className="calendar-rows" aria-hidden="true">
            {ROWS.map((name, i) => (
              <span key={i}>{name}</span>
            ))}
          </div>
          <div className="calendar-grid" role="img" aria-label={`Use by day: ${grid.activeDays} active days in the past year`}>
            {grid.weeks.map((week, w) =>
              week.map((cell, d) => (
                <span
                  key={cell.day}
                  className="calendar-cell"
                  data-level={cell.level}
                  data-future={cell.future || undefined}
                  style={{ gridColumn: w + 1, gridRow: d + 1 }}
                  onMouseEnter={(event) => {
                    if (cell.future) return setHover(null);
                    const box = event.currentTarget.getBoundingClientRect();
                    const frame = event.currentTarget.closest(".calendar")?.getBoundingClientRect();
                    setHover({ cell, x: box.left + box.width / 2 - (frame?.left ?? 0), y: box.top - (frame?.top ?? 0) });
                  }}
                />
              )),
            )}
          </div>
        </div>
      </div>
      {hover && (
        <div className="calendar-tip" style={{ left: hover.x, top: hover.y }} role="status">
          <strong>{dayLabel(hover.cell.day)}</strong>
          {hover.cell.used ? (
            <span>
              {tokens(hover.cell.used.tokens)} tokens · {dollars(hover.cell.used.dollars)} ·{" "}
              {plural(hover.cell.used.sessions, "session")}
            </span>
          ) : (
            <span className="muted">Nothing used</span>
          )}
        </div>
      )}
      <div className="calendar-legend" aria-hidden="true">
        <span className="muted small">Less</span>
        {[0, 1, 2, 3, 4].map((n) => (
          <span key={n} className="calendar-cell" data-level={n} />
        ))}
        <span className="muted small">More</span>
      </div>
      <span className="sr-only">{grid.weeks.flat().filter((c) => c.used).map(describe).join(". ")}</span>
    </div>
  );
}
