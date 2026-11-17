/**
 * The four themes. The choice lives in localStorage; "system" follows macOS light and dark
 * mode with the two plain themes. layout.tsx runs THEME_SCRIPT before the first paint, so a
 * page never flashes the wrong colors.
 */

export const THEMES = [
  { id: "paper", name: "Paper", about: "Light and plain" },
  { id: "graphite", name: "Graphite", about: "Dark and plain" },
  { id: "slate", name: "Blue Slate", about: "Cool blue-grey glass" },
  { id: "mustard", name: "Mustard Charcoal", about: "Warm charcoal, mustard accent" },
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
