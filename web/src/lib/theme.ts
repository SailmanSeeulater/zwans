/**
 * The themes. The choice lives in localStorage; "system" follows the system's light and
 * dark mode with the two plain themes. layout.tsx runs THEME_SCRIPT before the first paint,
 * so a page never flashes the wrong colors. Each theme's colors are in app/globals.css.
 */

export const THEMES = [
  { id: "paper", name: "Paper", about: "Light and plain", dark: false },
  { id: "chalk", name: "Chalk", about: "White, with ink for an accent", dark: false },
  { id: "lagoon", name: "Lagoon", about: "White, teal accent", dark: false },
  { id: "orchid", name: "Orchid", about: "White, violet accent", dark: false },
  { id: "ember", name: "Ember", about: "White, burnt orange accent", dark: false },
  { id: "fern", name: "Fern", about: "White, green accent", dark: false },
  { id: "sand", name: "Sand", about: "Warm cream, terracotta accent", dark: false },
  { id: "mint", name: "Mint", about: "Pale green, deep green accent", dark: false },
  { id: "lilac", name: "Lilac", about: "Pale violet, indigo accent", dark: false },
  { id: "sky", name: "Sky", about: "Pale blue, navy accent", dark: false },
  { id: "blush", name: "Blush", about: "Pale rose, wine accent", dark: false },
  { id: "graphite", name: "Graphite", about: "Dark and plain", dark: true },
  { id: "slate", name: "Blue Slate", about: "Cool blue-grey glass", dark: true },
  { id: "mustard", name: "Mustard Charcoal", about: "Warm charcoal, mustard accent", dark: true },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];
export type ThemeChoice = ThemeId | "system";

const KEY = "zwans-theme";
const IDS: readonly string[] = THEMES.map((theme) => theme.id);

export function readChoice(): ThemeChoice {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && (saved === "system" || IDS.includes(saved))) return saved as ThemeChoice;
  } catch {
    // Storage can be blocked; the default is fine.
  }
  return "system";
}

export function resolve(choice: ThemeChoice): ThemeId {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "graphite" : "paper";
}

export function chooseTheme(choice: ThemeChoice) {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // Still applies for this page.
  }
  document.documentElement.dataset.theme = resolve(choice);
}

/** Runs in <head> before anything paints. Kept tiny and dependency-free. */
export const THEME_SCRIPT = `(function(){var d=document.documentElement,c="system";try{c=localStorage.getItem("${KEY}")||"system"}catch(e){}
function a(){var t=c;if(t==="system"||${JSON.stringify(IDS)}.indexOf(t)<0){t=matchMedia("(prefers-color-scheme: dark)").matches?"graphite":"paper"}d.dataset.theme=t}
a();matchMedia("(prefers-color-scheme: dark)").addEventListener("change",function(){try{c=localStorage.getItem("${KEY}")||"system"}catch(e){}a()});
if(window.zwansDesktop){d.dataset.desktop="1"}})();`;
