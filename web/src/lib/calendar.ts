/**
 * The Usage page's calendar: a year of days in week columns, Monday at the top, each
 * shaded by how much was used that day.
 */

export interface CalendarDay {
  day: string; // YYYY-MM-DD
  tokens: number;
  dollars: number;
  calls: number;
  sessions: number;
}

export interface UsageCalendar {
  start: string; // a Monday
  end: string; // today
  days: CalendarDay[]; // only the days with any use, oldest first
}

export interface Cell {
  day: string;
  used: CalendarDay | null;
  level: 0 | 1 | 2 | 3 | 4;
  future: boolean; // after today, in this week's column
}

export interface CalendarGrid {
  weeks: Cell[][]; // columns, oldest first, seven cells each
  months: { column: number; label: string }[];
  activeDays: number;
  longestStreak: number;
  currentStreak: number;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86_400_000;

// Dates as UTC midnights, so adding days never meets a clock change.
const parse = (day: string) => Date.UTC(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)));
const format = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/**
 * A day's shade, 1 to 4, from how its use compares with the busiest day's. The square root
 * spreads the quiet days out, so one huge day doesn't leave every other one at the bottom.
 */
export function level(value: number, most: number): Cell["level"] {
  if (!(value > 0) || !(most > 0)) return 0;
  return (1 + Math.min(3, Math.floor(4 * Math.sqrt(value / most) - 1e-9))) as Cell["level"];
}

export function calendarGrid(calendar: UsageCalendar, measure: "tokens" | "dollars"): CalendarGrid {
  const byDay = new Map(calendar.days.map((d) => [d.day, d]));
  const most = Math.max(0, ...calendar.days.map((d) => d[measure]));
  const start = parse(calendar.start);
  const end = parse(calendar.end);
  const weeks: Cell[][] = [];
  const months: CalendarGrid["months"] = [];
  let lastMonth = -1;
  for (let week = start; week <= end; week += 7 * DAY_MS) {
    const cells: Cell[] = [];
    for (let i = 0; i < 7; i++) {
      const day = format(week + i * DAY_MS);
      const used = byDay.get(day) ?? null;
      cells.push({ day, used, level: used ? level(used[measure], most) : 0, future: week + i * DAY_MS > end });
    }
    // A month's label goes over the first column that starts in it.
    const month = new Date(week).getUTCMonth();
    if (month !== lastMonth) {
      if (lastMonth !== -1 || new Date(week).getUTCDate() <= 7) months.push({ column: weeks.length, label: MONTHS[month] ?? "" });
      lastMonth = month;
    }
    weeks.push(cells);
  }

  let longest = 0;
  let run = 0;
  for (let day = start; day <= end; day += DAY_MS) {
    run = byDay.has(format(day)) ? run + 1 : 0;
    longest = Math.max(longest, run);
  }
  // Today not used yet doesn't break the streak; it can still be.
  let current = 0;
  for (let day = byDay.has(format(end)) ? end : end - DAY_MS; day >= start && byDay.has(format(day)); day -= DAY_MS) current += 1;

  return { weeks, months, activeDays: calendar.days.length, longestStreak: longest, currentStreak: current };
}

/** "Thu, Nov 19", for a day's tooltip. */
export function dayLabel(day: string): string {
  const date = new Date(parse(day));
  const weekday = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][date.getUTCDay()];
  return `${weekday}, ${MONTHS[date.getUTCMonth()]} ${date.getUTCDate()}`;
}
