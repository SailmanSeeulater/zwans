import { useSyncExternalStore } from "react";

const never = () => () => {};

/** Whether this is a Mac, to name keys the way its keyboard does. Counts as a Mac until the
 * page has mounted, since that is what the static export renders. */
export function useIsMac(): boolean {
  return useSyncExternalStore(
    never,
    () => /Mac|iPhone|iPad/.test(navigator.platform),
    () => true,
  );
}

/** A shortcut with the platform's modifier: ⌘K on a Mac, Ctrl+K elsewhere. */
export function shortcut(mac: boolean, key: string): string {
  return mac ? `⌘${key}` : `Ctrl+${key}`;
}
