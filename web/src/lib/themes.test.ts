import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { contrast, over, parseColor, type Rgba } from "./contrast";
import { THEMES } from "./theme";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

/** A theme's tokens, read from its block in globals.css. */
function tokens(id: string): Record<string, string> {
  const block = new RegExp(`\\[data-theme="${id}"\\]\\s*\\{([^}]*)\\}`).exec(css);
  if (!block) throw new Error(`globals.css has no block for the theme ${id}`);
  const found: Record<string, string> = {};
  for (const [, name, value] of block[1]!.matchAll(/--([\w-]+):\s*([^;]+);/g)) found[name!] = value!.trim();
  return found;
}

/** Every pairing of text and what it sits on, with the ratio each must reach. */
function pairings(t: Record<string, string>): [what: string, text: Rgba, on: Rgba, least: number][] {
  const color = (name: string) => parseColor(t[name] === "var(--base)" ? t.base! : t[name]!);
  const page = color("base");
  const panel = over(color("glass"), page);
  const control = over(color("raised"), panel);
  const tint = over(color("accent-soft"), panel);
  return [
    ["text on the page", color("ink"), page, 7],
    ["text on a panel", color("ink"), panel, 7],
    ["text on a control", color("ink"), control, 7],
    ["quiet text on the page", color("ink-2"), page, 4.5],
    ["quiet text on a panel", color("ink-2"), panel, 4.5],
    ["a link on the page", color("accent"), page, 4.5],
    ["a link on a panel", color("accent"), panel, 4.5],
    ["the accent on its own tint", color("accent"), tint, 4.5],
    ["a primary button's label", color("accent-ink"), color("accent"), 4.5],
    ["passed, on a panel", color("ok"), panel, 4.5],
    ["failed, on a panel", color("bad"), panel, 4.5],
    ["a warning, on a panel", color("warn"), panel, 4.5],
    ["the context map's first tile", color("on-s1"), color("s1"), 4.5],
    ["the context map's second tile", color("on-s2"), color("s2"), 4.5],
    ["the context map's third tile", color("on-s3"), color("s3"), 4.5],
    ["the context map's fourth tile", color("on-s4"), color("s4"), 4.5],
  ];
}

describe("themes", () => {
  it.each(THEMES.map((theme) => [theme.name, theme.id]))("%s can be read", (_, id) => {
    const low = pairings(tokens(id))
      .map(([what, text, on, least]) => ({ what, ratio: contrast(text, on), least }))
      .filter((pair) => pair.ratio < pair.least)
      .map((pair) => `${pair.what}: ${pair.ratio.toFixed(2)}, needs ${pair.least}`);

    expect(low).toEqual([]);
  });

  it("has ten light themes beyond Paper, at least half of them on a white page", () => {
    const light = THEMES.filter((theme) => !theme.dark && theme.id !== "paper");
    const white = light.filter((theme) => tokens(theme.id).base === "#ffffff");

    expect(light).toHaveLength(10);
    expect(white.length).toBeGreaterThanOrEqual(5);
    // A light theme says so to the browser, which draws its own controls to match.
    for (const theme of THEMES) {
      expect(css).toMatch(
        new RegExp(`\\[data-theme="${theme.id}"\\]\\s*\\{[^}]*color-scheme: ${theme.dark ? "dark" : "light"};`),
      );
    }
  });
});

describe("contrast", () => {
  it("is 21 for black on white and 1 for a colour on itself", () => {
    expect(contrast(parseColor("#000000"), parseColor("#ffffff"))).toBeCloseTo(21);
    expect(contrast(parseColor("#777777"), parseColor("rgb(119, 119, 119)"))).toBeCloseTo(1);
    expect(over(parseColor("rgba(0, 0, 0, 0.5)"), parseColor("#ffffff"))).toEqual([127.5, 127.5, 127.5, 1]);
  });
});
