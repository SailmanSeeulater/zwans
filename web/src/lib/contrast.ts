/** How readable one colour is on another, by the WCAG contrast ratio. */

export type Rgba = [red: number, green: number, blue: number, alpha: number];

/** A colour written as #rrggbb or rgb()/rgba(), as the theme tokens are. */
export function parseColor(text: string): Rgba {
  const value = text.trim();
  if (value.startsWith("#")) {
    const hex = value.slice(1);
    const part = (i: number) => parseInt(hex.slice(i, i + 2), 16);
    return [part(0), part(2), part(4), 1];
  }
  const numbers = (value.match(/[\d.]+/g) ?? []).map(Number);
  if (!value.startsWith("rgb") || numbers.length < 3) throw new Error(`Not a colour: ${text}`);
  return [numbers[0]!, numbers[1]!, numbers[2]!, numbers[3] ?? 1];
}

/** What a see-through colour looks like on top of a solid one. */
export function over(top: Rgba, bottom: Rgba): Rgba {
  const [r, g, b, a] = top;
  return [r * a + bottom[0] * (1 - a), g * a + bottom[1] * (1 - a), b * a + bottom[2] * (1 - a), 1];
}

function luminance([r, g, b]: Rgba): number {
  const channel = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** From 1 (the same colour) to 21 (black on white). Body text needs 4.5. */
export function contrast(a: Rgba, b: Rgba): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (light + 0.05) / (dark + 0.05);
}
