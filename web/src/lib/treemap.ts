/**
 * A squarified treemap (Bruls, Huizing and van Wijk): tiles whose areas match their values,
 * laid out row by row so each tile stays close to square.
 */

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function squarify<T extends { value: number }>(items: T[], box: Rect): (T & { rect: Rect })[] {
  const total = items.reduce((sum, item) => sum + Math.max(item.value, 0), 0);
  if (total <= 0 || box.w <= 0 || box.h <= 0) return [];
  const scale = (box.w * box.h) / total;
  const queue = items
    .filter((item) => item.value > 0)
    .map((item) => ({ item, area: item.value * scale }))
    .sort((a, b) => b.area - a.area);

  const out: (T & { rect: Rect })[] = [];
  let free = { ...box };
  let row: typeof queue = [];

  const worst = (areas: number[], side: number): number => {
    const sum = areas.reduce((a, b) => a + b, 0);
    const max = Math.max(...areas);
    const min = Math.min(...areas);
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  };

  const place = () => {
    const sum = row.reduce((a, r) => a + r.area, 0);
    const horizontal = free.w >= free.h; // lay the row along the shorter side
    if (horizontal) {
      const width = sum / free.h;
      let y = free.y;
      for (const r of row) {
        const h = r.area / width;
        out.push({ ...r.item, rect: { x: free.x, y, w: width, h } });
        y += h;
      }
      free = { x: free.x + width, y: free.y, w: free.w - width, h: free.h };
    } else {
      const height = sum / free.w;
      let x = free.x;
      for (const r of row) {
        const w = r.area / height;
        out.push({ ...r.item, rect: { x, y: free.y, w, h: height } });
        x += w;
      }
      free = { x: free.x, y: free.y + height, w: free.w, h: free.h - height };
    }
    row = [];
  };

  for (const next of queue) {
    const side = Math.min(free.w, free.h);
    const areas = row.map((r) => r.area);
    if (row.length === 0 || worst([...areas, next.area], side) <= worst(areas, side)) {
      row.push(next);
    } else {
      place();
      row.push(next);
    }
  }
  if (row.length) place();
  return out;
}
