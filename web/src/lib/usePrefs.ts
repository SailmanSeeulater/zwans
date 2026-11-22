"use client";

import { useSyncExternalStore } from "react";
import { applyPrefs, DEFAULT_PREFS, forgetPrefs, readPrefs, type Prefs } from "./prefs";

const KEY = "zwans-prefs";

function subscribe(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== KEY) return;
    forgetPrefs();
    applyPrefs(readPrefs());
    onChange();
  };
  window.addEventListener("zwans:prefs", onChange);
  window.addEventListener("storage", onStorage); // another tab changed them
  return () => {
    window.removeEventListener("zwans:prefs", onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, readPrefs, () => DEFAULT_PREFS);
}
