/** What /api/usage returns, and how the Usage page labels and scales it. */

export interface UsageTotal {
  calls: number;
  sessions: number;
  tokens: number; // the four kinds below, added up
  input_tokens: number; // sent at the full input price
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  dollars: number;
  unpriced_calls: number; // on a hosted model with no known price: tokens, no dollars
}

export type UsageBucket = UsageTotal & { start: string }; // the bucket's first day, YYYY-MM-DD
export type Period = "day" | "week" | "month" | "year";

export interface Usage {
  now: string;
  first: string | null; // the day of the first recorded call
  totals: Record<Period | "all", UsageTotal>;
  series: Record<Period, UsageBucket[]>; // oldest first, empty buckets included
  models: (UsageTotal & { model: string })[];
}

export const PERIODS: { id: Period; name: string; current: string; each: string }[] = [
  { id: "day", name: "Days", current: "Today", each: "Day" },
  { id: "week", name: "Weeks", current: "This week", each: "Week of" },
  { id: "month", name: "Months", current: "This month", each: "Month" },
  { id: "year", name: "Years", current: "This year", each: "Year" },
];

export const KINDS = [
  { key: "input_tokens", label: "Input", color: "var(--s1)" },
  { key: "cache_write_tokens", label: "Cache writes", color: "var(--s2)" },
  { key: "cache_read_tokens", label: "Cache reads", color: "var(--s3)" },
  { key: "output_tokens", label: "Output", color: "var(--s4)" },
] as const;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A bucket's name from its first day: "Nov 22", "Nov 16" for that week, "Nov 2026", "2026". */
export function bucketLabel(start: string, period: Period): string {
  const [year, month, day] = start.split("-").map(Number);
  const name = MONTHS[(month ?? 1) - 1] ?? "";
  if (period === "year") return String(year);
  if (period === "month") return `${name} ${year}`;
  return `${name} ${day}`;
}

/**
 * Round numbers for a chart's axis, from zero to at least `most`: about four steps of 1, 2,
 * 2.5 or 5 times a power of ten. An empty chart still gets an axis.
 */
export function axisTicks(most: number, steps = 4): number[] {
  if (!(most > 0)) return [0, 1];
  const rough = most / steps;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const ticks = [];
  for (let i = 0; i * step < most + step; i++) ticks.push(Number((i * step).toPrecision(12)));
  return ticks;
}

/** Which bars get a label under them: about `wanted` of them, evenly, always the last. */
export function labelled(count: number, wanted = 8): Set<number> {
  const every = Math.max(1, Math.ceil(count / wanted));
  const shown = new Set<number>();
  for (let i = count - 1; i >= 0; i -= every) shown.add(i);
  return shown;
}
