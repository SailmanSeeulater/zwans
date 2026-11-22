/**
 * How Zwans looks and behaves for this person: accent, text size, density, width, motion,
 * thinking, notifications and what a new session starts with. Kept in localStorage, and put on
 * <html> as data attributes before the first paint (PREFS_SCRIPT), as the theme is.
 */
export const ACCENTS = [
  { id: "theme", name: "Theme's own" },
  { id: "blue", name: "Blue", light: "#0b63ce", dark: "#5e9eff" },
  { id: "violet", name: "Violet", light: "#6d33d6", dark: "#a98bff" },
  { id: "teal", name: "Teal", light: "#0b6f6a", dark: "#3fc2b8" },
  { id: "green", name: "Green", light: "#17753c", dark: "#5fcf86" },
  { id: "orange", name: "Orange", light: "#b8400d", dark: "#ff9d5c" },
  { id: "pink", name: "Pink", light: "#b8336a", dark: "#ff8fbd" },
] as const;

export type Accent = (typeof ACCENTS)[number]["id"];

export interface Prefs {
  accent: Accent;
  text: "small" | "medium" | "large";
  density: "comfortable" | "compact";
  width: "normal" | "wide";
  motion: "system" | "full" | "reduced";
  thinking: "folded" | "open";
  notifyDone: boolean;
  notifyWaiting: boolean;
  sound: boolean;
  newMode: "read-only" | "ask" | "auto";
  newModel: string; // "" for the config's
}

export const DEFAULT_PREFS: Prefs = {
  accent: "theme",
  text: "medium",
  density: "comfortable",
  width: "normal",
  motion: "system",
  thinking: "folded",
  notifyDone: true,
  notifyWaiting: true,
  sound: false,
  newMode: "ask",
  newModel: "",
};

const KEY = "zwans-prefs";
const CHOICES: { [K in keyof Prefs]?: readonly string[] } = {
  accent: ACCENTS.map((a) => a.id),
  text: ["small", "medium", "large"],
  density: ["comfortable", "compact"],
  width: ["normal", "wide"],
  motion: ["system", "full", "reduced"],
  thinking: ["folded", "open"],
  newMode: ["read-only", "ask", "auto"],
};

/** Saved preferences made safe to use: anything missing or not one of its choices is the default. */
export function restorePrefs(saved: unknown): Prefs {
  const from = typeof saved === "object" && saved !== null ? (saved as Record<string, unknown>) : {};
  const prefs: Record<string, unknown> = { ...DEFAULT_PREFS };
  for (const key of Object.keys(DEFAULT_PREFS) as (keyof Prefs)[]) {
    const value = from[key];
    const fallback = DEFAULT_PREFS[key];
    const choices = CHOICES[key];
    if (choices ? typeof value === "string" && choices.includes(value) : typeof value === typeof fallback) {
      prefs[key] = value;
    }
  }
  return prefs as unknown as Prefs;
}

let cached: Prefs | null = null;

/** Forget the cached copy, after another tab saved new ones. */
export function forgetPrefs() {
  cached = null;
}

export function readPrefs(): Prefs {
  if (cached) return cached;
  try {
    cached = restorePrefs(JSON.parse(localStorage.getItem(KEY) ?? "{}"));
  } catch {
    cached = DEFAULT_PREFS;
  }
  return cached;
}

export function savePrefs(change: Partial<Prefs>): Prefs {
  const next = restorePrefs({ ...readPrefs(), ...change });
  cached = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Still applies to this page.
  }
  applyPrefs(next);
  window.dispatchEvent(new Event("zwans:prefs"));
  return next;
}

/** The data attributes the stylesheet reads. */
export function prefAttributes(prefs: Prefs): Record<string, string> {
  return {
    accent: prefs.accent,
    text: prefs.text,
    density: prefs.density,
    width: prefs.width,
    motion: prefs.motion,
  };
}

export function applyPrefs(prefs: Prefs) {
  Object.assign(document.documentElement.dataset, prefAttributes(prefs));
}

/** Runs in <head> before anything paints. Only the attributes; the rest waits for React. */
export const PREFS_SCRIPT = `(function(){try{var p=JSON.parse(localStorage.getItem("${KEY}")||"{}"),d=document.documentElement.dataset,c=${JSON.stringify(
  Object.fromEntries(["accent", "text", "density", "width", "motion"].map((k) => [k, CHOICES[k as keyof Prefs]])),
)};for(var k in c){d[k]=c[k].indexOf(p[k])>=0?p[k]:c[k][k==="text"?1:0]}}catch(e){}})();`;
