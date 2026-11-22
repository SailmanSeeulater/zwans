/** Numbers as the UI shows them. */

/** 1234 → "1.2k", 1234567 → "1.23M". */
export function tokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(Math.round(n));
}

/** Dollars with enough digits to tell small amounts apart. */
export function dollars(n: number | null | undefined): string {
  if (n === null || n === undefined) return "–";
  if (n === 0) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(3)}`;
  return `$${n.toFixed(2)}`;
}

/** A run's total, to the cent, without rounding a small amount down to nothing. */
export function spent(n: number): string {
  return n > 0 && n < 0.005 ? "<$0.01" : `$${n.toFixed(2)}`;
}

export function seconds(n: number): string {
  if (n < 1) return `${n.toFixed(2)} s`;
  if (n < 60) return `${n.toFixed(1)} s`;
  return `${Math.floor(n / 60)} min ${Math.round(n % 60)} s`;
}

export const pct = (x: number): string => `${Math.round(x * 100)}%`;

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/** The last line of some text that has anything on it, or "" when none does. */
export function lastLine(text: string): string {
  const lines = text.split("\n").map((line) => line.trim());
  return lines.filter(Boolean).at(-1) ?? "";
}

/** Text split at its `backticks`, so the parts between a pair can be shown as code. Text
 * with an unpaired backtick comes back whole. */
export function codeSpans(text: string): { text: string; code: boolean }[] {
  const parts = text.split("`");
  if (parts.length % 2 === 0) return [{ text, code: false }];
  return parts.map((part, i) => ({ text: part, code: i % 2 === 1 })).filter((span) => span.text);
}
