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

export function seconds(n: number): string {
  if (n < 1) return `${n.toFixed(2)} s`;
  if (n < 60) return `${n.toFixed(1)} s`;
  return `${Math.floor(n / 60)} min ${Math.round(n % 60)} s`;
}

export const pct = (x: number): string => `${Math.round(x * 100)}%`;

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}
