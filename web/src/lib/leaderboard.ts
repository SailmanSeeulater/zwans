/** The leaderboard chart's cost axis. */

export interface Scale {
  /** Where a cost sits along the axis, from 0 (left) to 1 (right). */
  at: (cost: number) => number;
  ticks: number[];
  log: boolean;
}

const FAR_APART = 20; // dearest over cheapest, beyond which a linear axis squashes the cheap ones

/** A linear axis from zero, or a log axis when the costs are far apart, so the cheap rows
 * don't pile up at the left edge. A log axis can't show a cost of zero, so a free row (a
 * local model) keeps the axis linear. */
export function costScale(costs: number[]): Scale {
  const max = Math.max(0, ...costs);
  const min = Math.min(...costs);
  if (costs.length > 1 && min > 0 && max / min > FAR_APART) {
    const low = Math.log10(min / 1.5);
    const high = Math.log10(max * 1.5);
    const ticks: number[] = [];
    for (let power = Math.floor(low); power <= Math.ceil(high); power += 1) {
      for (const step of [1, 2, 5]) {
        const tick = step * 10 ** power;
        if (Math.log10(tick) >= low && Math.log10(tick) <= high) ticks.push(tick);
      }
    }
    return { at: (cost) => (Math.log10(cost) - low) / (high - low), ticks, log: true };
  }
  const top = max > 0 ? max * 1.1 : 1;
  return { at: (cost) => cost / top, ticks: [0, 0.25, 0.5, 0.75, 1].map((f) => f * top), log: false };
}

/** The pass rates the chart's other axis marks, lowest first, ending at 100%. It starts as
 * high as the rows allow, so rows that all pass most of the time aren't squeezed against the
 * top, and it only starts at round numbers. */
export function rateTicks(rates: number[]): number[] {
  const lowest = Math.min(1, ...rates);
  const [floor, steps] = lowest >= 0.92 ? [0.9, 5] : lowest >= 0.85 ? [0.8, 4] : lowest >= 0.55 ? [0.5, 5] : [0, 4];
  return Array.from({ length: steps + 1 }, (_, i) => floor + (i * (1 - floor)) / steps);
}
