import { describe, expect, it } from "vitest";
import { DEFAULT_PREFS, PREFS_SCRIPT, prefAttributes, restorePrefs } from "./prefs";

describe("restorePrefs", () => {
  it("keeps what's valid and falls back for the rest", () => {
    const prefs = restorePrefs({ accent: "violet", text: "huge", density: "compact", sound: "yes", newModel: "ollama/x" });
    expect(prefs.accent).toBe("violet");
    expect(prefs.text).toBe("medium");
    expect(prefs.density).toBe("compact");
    expect(prefs.sound).toBe(false);
    expect(prefs.newModel).toBe("ollama/x");
  });

  it("is the defaults for anything that isn't saved preferences", () => {
    expect(restorePrefs(null)).toEqual(DEFAULT_PREFS);
    expect(restorePrefs("x")).toEqual(DEFAULT_PREFS);
  });
});

describe("PREFS_SCRIPT", () => {
  // The script runs before React, so it has to agree with prefAttributes on its own.
  function run(saved: string | null): Record<string, string> {
    const dataset: Record<string, string> = {};
    const env = {
      localStorage: { getItem: () => saved },
      document: { documentElement: { dataset } },
    };
    new Function("localStorage", "document", PREFS_SCRIPT)(env.localStorage, env.document);
    return dataset;
  }

  it("sets the same attributes React would, defaults included", () => {
    expect(run(null)).toEqual(prefAttributes(DEFAULT_PREFS));
    const saved = { ...DEFAULT_PREFS, accent: "pink", text: "large", width: "wide", motion: "reduced" } as const;
    expect(run(JSON.stringify(saved))).toEqual(prefAttributes(saved));
  });

  it("ignores values it doesn't know", () => {
    expect(run(JSON.stringify({ accent: "plaid", text: "huge" }))).toEqual(prefAttributes(DEFAULT_PREFS));
  });
});
